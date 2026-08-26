"""JSON-first commands for the human-approved delivery chain.

Four separate commands for four separate capabilities. `preview` never approves,
`approve` never sends, and `send` handles exactly one application per invocation.
There is deliberately no command that walks a list.
"""

import json
import sys
from pathlib import Path
from typing import Annotated, Never, NoReturn, TypeVar

import typer
from pydantic import ValidationError

from jobagent.applications.approval import (
    ApplicationApprovalService,
    compute_digests,
    verify_approval_is_current,
)
from jobagent.applications.audit import ApplicationAuditor
from jobagent.applications.delivery import DeliveryGate
from jobagent.applications.ports import ApplicationDeliverySource
from jobagent.applications.preview import ApplicationPreviewService
from jobagent.connectors.factory import build_delivery_source
from jobagent.errors import (
    ApprovalRequiredError,
    ContractValidationError,
    JobAgentError,
    UnverifiedResumeVariantError,
    UserInterventionRequiredError,
)
from jobagent.schemas.applications import (
    ApplicationPackage,
    ApprovalRecord,
    DeliveryPolicy,
    DeliveryRequest,
)
from jobagent.schemas.common import ContractModel
from jobagent.schemas.jobs import MatchResult, NormalizedJob
from jobagent.schemas.optimizer import ResumeVariant
from jobagent.storage.application_repository import SqliteApplicationAuditRepository
from jobagent.storage.database import Database

DEFAULT_DATABASE = Path(".jobagent/jobagent.sqlite3")
DatabaseOption = Annotated[Path, typer.Option("--database", help="Local SQLite path.")]
ModelT = TypeVar("ModelT", bound=ContractModel)

applications_app = typer.Typer(
    help="Review, approve, deliver and audit one application at a time.",
    no_args_is_help=True,
)


def _no_connector_installed(platform: str) -> NoReturn:
    """Refuse to invent a platform connector.

    JobAgent ships the delivery port and a test double only. Until a reviewed
    connector is wired in, delivery is a human step, per
    `skills/job-hunting/references/stop-conditions.md`.
    """
    raise UserInterventionRequiredError(
        "No delivery connector is installed; submit this application yourself on the platform.",
        details={
            "platform": platform,
            "next_capability": "jobagent applications audit-log",
            "retryable": False,
        },
    )


def _installed_connector(platform: str) -> ApplicationDeliverySource:
    """Resolve a reviewed connector, or refuse.

    Platform names live in `connectors/`, never here: the delivery subsystem
    stays platform-agnostic so an unsupported board cannot be reached by accident.
    """
    source = build_delivery_source(platform)
    if source is None:
        _no_connector_installed(platform)
    return source


_connector_provider = _installed_connector


def _fail(error: JobAgentError) -> Never:
    typer.echo(
        json.dumps(
            {"error": {"code": error.code, "message": error.message, "details": error.details}},
            ensure_ascii=False,
        )
    )
    raise typer.Exit(code=1)


def _confirmation_code(package: ApplicationPackage) -> str:
    """A short code bound to the exact artifacts being approved."""
    digests = compute_digests(package, DeliveryPolicy())
    return digests.job_digest.removeprefix("sha256:")[:6].upper()


def _require_interactive_confirmation(package: ApplicationPackage) -> None:
    """Refuse to approve unless a person is actually at the terminal.

    An automated caller has no TTY, so it cannot satisfy this. Platform tooling
    guards its own authorization step the same way, for the same reason.
    """
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise ApprovalRequiredError(
            "Approval must be given at an interactive terminal, by a person.",
            details={
                "application_id": package.application_id,
                "why": "an automated caller must not be able to approve on its own behalf",
            },
        )
    expected = _confirmation_code(package)
    typer.echo(
        "About to approve an application that can then be delivered:\n"
        f"  job:     {package.job.title} · {package.job.company}\n"
        f"  url:     {package.job.url}\n"
        f"  resume:  {package.resume_variant.id}\n"
        f"  message: {package.message[:60]}\n"
        f"Type {expected} to approve, anything else to abort: "
    )
    if input().strip().upper() != expected:
        raise ApprovalRequiredError(
            "Approval was not confirmed.",
            details={"application_id": package.application_id},
        )


def _emit_dry_run(
    package: ApplicationPackage,
    approval: ApprovalRecord,
    request: DeliveryRequest,
    source: ApplicationDeliverySource,
) -> None:
    """Report what a real send would do, having passed the same gates.

    The approval check runs here too: a rehearsal that skipped it would report a
    green result for a package that could never actually be delivered.
    """
    digests = compute_digests(package, DeliveryPolicy())
    verify_approval_is_current(approval, digests)
    if not package.resume_variant.verification.passed:
        raise UnverifiedResumeVariantError(
            "Resume variant failed verification and cannot be delivered.",
            details={"application_id": package.application_id},
        )
    typer.echo(
        json.dumps(
            {
                "dry_run": {
                    "would_send": True,
                    "application_id": request.application_id,
                    "platform": package.job.source,
                    "connector": type(source).__name__,
                    "job_id": package.job.source_job_id,
                    "job_kind": package.job.job_kind,
                    "job_title": package.job.title,
                    "company": package.job.company,
                    "resume_variant_id": package.resume_variant.id,
                    "approval_id": approval.approval_id,
                    "note": "No platform call was made and no audit record was written.",
                }
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _load_model(path: Path, model_type: type[ModelT]) -> ModelT:
    try:
        return model_type.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise ContractValidationError(
            "Reviewed JSON input could not be loaded.",
            details={"file_name": path.name, "contract": model_type.__name__},
        ) from error


def _load_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise ContractValidationError(
            "Message file could not be read.",
            details={"file_name": path.name},
        ) from error


def _emit(value: ContractModel) -> None:
    typer.echo(value.model_dump_json(indent=2))


def _auditor(path: Path) -> ApplicationAuditor:
    path.parent.mkdir(parents=True, exist_ok=True)
    database = Database(path)
    database.migrate()
    return ApplicationAuditor(SqliteApplicationAuditRepository(database))


@applications_app.command("preview")
def preview(
    application_id: Annotated[str, typer.Argument(help="Stable APP_* identifier.")],
    job_path: Annotated[Path, typer.Argument(help="NormalizedJob JSON.")],
    match_path: Annotated[Path, typer.Argument(help="MatchResult JSON.")],
    variant_path: Annotated[Path, typer.Argument(help="Verified ResumeVariant JSON.")],
    message_path: Annotated[Path, typer.Argument(help="Reviewed message text file.")],
    risk: Annotated[
        list[str] | None,
        typer.Option("--risk", help="Reviewer risk note; repeatable."),
    ] = None,
) -> None:
    """Assemble one reviewable package. This is not an approval."""
    try:
        _emit(
            ApplicationPreviewService().prepare(
                application_id=application_id,
                job=_load_model(job_path, NormalizedJob),
                match=_load_model(match_path, MatchResult),
                resume_variant=_load_model(variant_path, ResumeVariant),
                message=_load_text(message_path),
                risks=risk or [],
            )
        )
    except JobAgentError as error:
        _fail(error)


@applications_app.command("approve")
def approve(
    package_path: Annotated[Path, typer.Argument(help="ApplicationPackage JSON from preview.")],
    confirm: Annotated[
        bool,
        typer.Option("--confirm", help="Record that a person reviewed and approved this package."),
    ] = False,
) -> None:
    """Bind a human decision to the exact job, resume, message and policy.

    Approval is the one step an automated caller must not be able to perform for
    itself, so `--confirm` alone is not enough: the command also requires an
    interactive terminal and a code typed back from the summary it prints. The
    code is derived from the artifacts, so approving means having looked at them.

    This stops an agent that drives the CLI. It does not stop one that imports
    `ApplicationApprovalService` directly — that boundary is the CLI, not the
    library, and the distinction is documented rather than papered over.
    """
    try:
        package = _load_model(package_path, ApplicationPackage)
        if not confirm:
            raise ApprovalRequiredError(
                "Approval requires an explicit human confirmation.",
                details={"application_id": package.application_id},
            )
        _require_interactive_confirmation(package)
        _emit(
            ApplicationApprovalService().approve(
                package,
                DeliveryPolicy(),
                confirmed=True,
            )
        )
    except JobAgentError as error:
        _fail(error)


@applications_app.command("send")
def send(
    package_path: Annotated[Path, typer.Argument(help="ApplicationPackage JSON.")],
    approval_path: Annotated[Path, typer.Argument(help="ApprovalRecord JSON from approve.")],
    database: DatabaseOption = DEFAULT_DATABASE,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Run every gate and report what would be sent, without contacting the platform.",
        ),
    ] = False,
) -> None:
    """Deliver exactly one approved application, then record the attempt.

    `--dry-run` exercises the same gates and stops before the platform call, so a
    rehearsal can never reach a recruiter. It writes no audit record, because no
    attempt was made.
    """
    try:
        package = _load_model(package_path, ApplicationPackage)
        approval = _load_model(approval_path, ApprovalRecord)
        source: ApplicationDeliverySource = _connector_provider(package.job.source)
        digests = compute_digests(package, DeliveryPolicy())
        request = DeliveryRequest(
            application_id=package.application_id,
            approval=approval,
            job_digest=digests.job_digest,
            resume_digest=digests.resume_digest,
            message_digest=digests.message_digest,
            policy_digest=digests.policy_digest,
        )
        if dry_run:
            _emit_dry_run(package, approval, request, source)
            return
        gate = DeliveryGate(source=source, auditor=_auditor(database), policy=DeliveryPolicy())
        _emit(gate.send(request, package))
    except JobAgentError as error:
        _fail(error)


@applications_app.command("audit-log")
def audit_log(
    application_id: Annotated[
        str | None,
        typer.Option("--application-id", help="Restrict the log to one application."),
    ] = None,
    database: DatabaseOption = DEFAULT_DATABASE,
) -> None:
    """Read the append-only record of every delivery attempt."""
    try:
        audits = _auditor(database).list_audits(application_id)
        typer.echo(
            json.dumps(
                [audit.model_dump(mode="json") for audit in audits],
                ensure_ascii=False,
                indent=2,
            )
        )
    except JobAgentError as error:
        _fail(error)
