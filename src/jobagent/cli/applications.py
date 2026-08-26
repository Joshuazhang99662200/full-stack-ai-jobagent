"""JSON-first commands for the human-approved delivery chain.

Four separate commands for four separate capabilities. `preview` never approves,
`approve` never sends, and `send` handles exactly one application per invocation.
There is deliberately no command that walks a list.
"""

import json
from pathlib import Path
from typing import Annotated, Never, NoReturn, TypeVar

import typer
from pydantic import ValidationError

from jobagent.applications.approval import ApplicationApprovalService, compute_digests
from jobagent.applications.audit import ApplicationAuditor
from jobagent.applications.delivery import DeliveryGate
from jobagent.applications.ports import ApplicationDeliverySource
from jobagent.applications.preview import ApplicationPreviewService
from jobagent.connectors.factory import build_delivery_source
from jobagent.errors import ContractValidationError, JobAgentError, UserInterventionRequiredError
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
    """Bind a human decision to the exact job, resume, message and policy."""
    try:
        _emit(
            ApplicationApprovalService().approve(
                _load_model(package_path, ApplicationPackage),
                DeliveryPolicy(),
                confirmed=confirm,
            )
        )
    except JobAgentError as error:
        _fail(error)


@applications_app.command("send")
def send(
    package_path: Annotated[Path, typer.Argument(help="ApplicationPackage JSON.")],
    approval_path: Annotated[Path, typer.Argument(help="ApprovalRecord JSON from approve.")],
    database: DatabaseOption = DEFAULT_DATABASE,
) -> None:
    """Deliver exactly one approved application, then record the attempt."""
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
