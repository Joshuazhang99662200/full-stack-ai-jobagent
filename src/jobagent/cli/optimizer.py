"""Read-only discovery commands for Resume Optimizer capabilities."""

import json
import typing
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Never

import typer
from pydantic import ValidationError

from jobagent.errors import (
    AgentHandoffRequiredError,
    CapabilityRegistryError,
    ContractValidationError,
    JobAgentError,
)
from jobagent.optimizer.diffing import ResumeDiffBuilder
from jobagent.optimizer.index import CapabilityIndexLoader, CapabilityRegistryCompiler
from jobagent.optimizer.routing import RewriteLensRouter
from jobagent.optimizer.tailoring import ResumeTailor, TailoredDraft
from jobagent.optimizer.verification import ClaimVerifier
from jobagent.reasoning.handoff import AgentHandoffProvider
from jobagent.schemas.common import ContractModel
from jobagent.schemas.jobs import JobRequirementProfile
from jobagent.schemas.optimizer import BaseResumeDocument, ResumeVariant
from jobagent.schemas.optimizer_registry import CapabilityKind, CapabilityRegistrySnapshot
from jobagent.skill_resources import default_skill_root
from jobagent.storage.candidate_repository import SqliteCandidateRepository
from jobagent.storage.database import Database
from jobagent.storage.job_repository import SqliteJobRepository

DEFAULT_DATABASE = Path(".jobagent/jobagent.sqlite3")
DEFAULT_HANDOFF_DIR = Path(".jobagent/handoff")
DatabaseOption = Annotated[Path, typer.Option("--database", help="Local SQLite path.")]

ModelT = typing.TypeVar("ModelT", bound=ContractModel)


def _load(path: Path, model: type[ModelT]) -> ModelT:
    try:
        return model.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise ContractValidationError(
            f"{model.__name__} could not be loaded.",
            details={"path": str(path)},
        ) from error


def _repositories(path: Path) -> tuple[SqliteCandidateRepository, SqliteJobRepository]:
    path.parent.mkdir(parents=True, exist_ok=True)
    database = Database(path)
    database.migrate()
    return SqliteCandidateRepository(database), SqliteJobRepository(database)

INDEX_PATHS = (
    Path("optimizer/index/repository.yaml"),
    Path("optimizer/index/policies.yaml"),
)


def _default_skill_root() -> Path:
    return default_skill_root()


optimizer_app = typer.Typer(
    help="Inspect Resume Optimizer capabilities.",
    no_args_is_help=True,
)


def _compile_snapshot() -> CapabilityRegistrySnapshot:
    return CapabilityRegistryCompiler(
        CapabilityIndexLoader(_default_skill_root())
    ).compile(INDEX_PATHS)


_snapshot_provider: Callable[[], CapabilityRegistrySnapshot] = _compile_snapshot


def _fail(error: JobAgentError) -> Never:
    typer.echo(
        json.dumps(
            {
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "details": error.details,
                }
            },
            ensure_ascii=False,
        )
    )
    raise typer.Exit(code=1)


@optimizer_app.command("capabilities")
def capabilities(
    kind: Annotated[
        CapabilityKind | None,
        typer.Option(
            "--kind",
            help="Return only entries of this capability kind.",
            case_sensitive=False,
        ),
    ] = None,
    intent: Annotated[
        str | None,
        typer.Option("--intent", help="Return only entries declaring this exact intent."),
    ] = None,
) -> None:
    """Inspect the checked-in capability index without loading indexed resources."""
    try:
        if intent is not None:
            intent = intent.strip()
            if not intent:
                raise ContractValidationError(
                    "Capability intent filter is invalid.",
                    details={"field": "intent"},
                )
        snapshot = _snapshot_provider()
        if kind is None and intent is None:
            typer.echo(snapshot.model_dump_json(indent=2))
            return

        entries = tuple(
            entry
            for entry in snapshot.entries
            if (kind is None or entry.kind is kind)
            and (intent is None or intent in entry.intents)
        )
        typer.echo(
            json.dumps(
                {
                    "schema_version": snapshot.schema_version,
                    "source_digest": snapshot.digest,
                    "entries": [entry.model_dump(mode="json") for entry in entries],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    except (CapabilityRegistryError, ContractValidationError) as error:
        _fail(error)


@optimizer_app.command("tailor")
def tailor(
    candidate_id: str,
    job_id: str,
    base_resume_path: Path,
    requirements_path: Path,
    database: DatabaseOption = DEFAULT_DATABASE,
    handoff_dir: Annotated[Path, typer.Option("--handoff-dir")] = DEFAULT_HANDOFF_DIR,
    target_role: Annotated[str, typer.Option("--target-role")] = "",
    variant_id: Annotated[str, typer.Option("--variant-id")] = "RESUME_VARIANT_001",
) -> None:
    """Emit a tailoring request for the calling agent, using the routed lens.

    The lens is selected from the recruiter observed on the job record, not chosen
    by hand. The agent writes back items plus a claim ledger; `assemble` then
    verifies it. Nothing here can mark a variant as passing.
    """
    try:
        base_resume = _load(base_resume_path, BaseResumeDocument)
        requirements = _load(requirements_path, JobRequirementProfile)
        candidates, jobs = _repositories(database)
        evidence = candidates.list_evidence(candidate_id)
        job = jobs.get_job(job_id)
        lens = RewriteLensRouter().select(job.recruiter if job is not None else None)

        ResumeTailor(AgentHandoffProvider(handoff_dir)).tailor(
            base_resume=base_resume,
            requirements=requirements,
            evidence=evidence,
            lens=lens,
            target_role=target_role or requirements.job_id,
            variant_id=variant_id,
        )
    except AgentHandoffRequiredError as handoff:
        details = dict(handoff.details)
        details["lens"] = lens.lens.value
        details["lens_reason"] = lens.reason
        typer.echo(
            json.dumps(
                {"handoff": {"code": handoff.code, "message": handoff.message, "details": details}},
                ensure_ascii=False,
                indent=2,
            )
        )
    except JobAgentError as error:
        _fail(error)


@optimizer_app.command("assemble")
def assemble(
    draft_path: Path,
    candidate_id: str,
    job_id: str,
    base_resume_path: Path,
    database: DatabaseOption = DEFAULT_DATABASE,
    variant_id: Annotated[str, typer.Option("--variant-id")] = "RESUME_VARIANT_001",
) -> None:
    """Verify an agent-written tailoring draft and assemble the variant.

    Exits non-zero when a quality gate fails. A failing variant is still emitted
    in full, because the issues are what a person needs in order to fix it.
    """
    try:
        draft = _load(draft_path, TailoredDraft)
        base_resume = _load(base_resume_path, BaseResumeDocument)
        candidates, _ = _repositories(database)
        confirmed = [item for item in candidates.list_evidence(candidate_id) if item.user_confirmed]

        verification = ClaimVerifier().verify(draft.claim_ledger, confirmed)
        diff = ResumeDiffBuilder().build(base_resume.items, draft.items)
        variant = ResumeVariant(
            id=variant_id,
            target_job_id=job_id,
            target_role=job_id,
            selected_evidence_ids=sorted(
                {item for claim in draft.claim_ledger.claims for item in claim.evidence_ids}
            ),
            items=list(draft.items),
            claim_ledger=draft.claim_ledger,
            keyword_coverage=draft.keyword_coverage,
            verification=verification,
            diff=diff,
            prompt_bundle_digest=base_resume.source_digest,
            generated_at=datetime.now(UTC),
        )
        typer.echo(variant.model_dump_json(indent=2))
        if not verification.passed:
            raise typer.Exit(code=1)
    except ValidationError as error:
        _fail(
            ContractValidationError(
                "The assembled variant did not satisfy its contract.",
                details={"variant_id": variant_id, "error_count": error.error_count()},
            )
        )
    except JobAgentError as error:
        _fail(error)
