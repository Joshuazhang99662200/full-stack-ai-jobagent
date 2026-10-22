"""Online profile commands: keep what each board shows, and change it only as approved.

The host reads the person's profile on a board in their own signed-in browser and
hands the sections over here; each read is kept whole and a new version opens only
when the words change. A change goes propose -> ask -> approve -> gate, then the
host edits the board and `record` checks a fresh read-back against the approved
profile. The repository never touches a board itself.
"""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Never

import typer
from pydantic import TypeAdapter, ValidationError

from jobagent.errors import ApprovalRequiredError, ContractValidationError, JobAgentError
from jobagent.evals.profile import next_profile_version, profile_digest
from jobagent.evals.profile_flywheel import ProfileFlywheel
from jobagent.schemas.profile import (
    ProfileApplyResult,
    ProfileField,
    ProfileProposal,
    ProfileProposalDraft,
    ProfileSnapshot,
    ProfileVersion,
)
from jobagent.sources import SourceRegistry
from jobagent.storage.candidate_repository import SqliteCandidateRepository
from jobagent.storage.database import Database
from jobagent.storage.evals_repository import SqliteEvalsRepository

profile_app = typer.Typer(
    help="Online profile snapshots, versions and approved changes.", no_args_is_help=True
)
FLYWHEEL = ProfileFlywheel()

DatabaseOption = Annotated[Path, typer.Option("--database", help="Local SQLite path.")]
DEFAULT_DATABASE = Path(".jobagent/jobagent.sqlite3")


def _emit(value: object) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _fail(error: JobAgentError) -> Never:
    typer.echo(
        json.dumps(
            {"error": {"code": error.code, "message": error.message, "details": error.details}},
            ensure_ascii=False,
        )
    )
    raise typer.Exit(1)


def _now(value: str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        raise ContractValidationError("--now needs a timezone offset.")
    return moment.astimezone(UTC)


def _store(database: Path) -> SqliteEvalsRepository:
    database.parent.mkdir(parents=True, exist_ok=True)
    db = Database(database)
    db.migrate()
    return SqliteEvalsRepository(db)


def _read_snapshot(path: Path, platform: str, moment: datetime) -> ProfileSnapshot:
    try:
        fields = TypeAdapter(list[ProfileField]).validate_json(path.read_bytes())
    except (OSError, ValidationError):
        raise ContractValidationError(
            "The profile file must hold a JSON list of sections.",
            details={"file_name": path.name},
        ) from None
    if not fields:
        raise ContractValidationError("A profile snapshot needs at least one section.")
    try:
        return ProfileSnapshot(
            snapshot_id=f"PROFSNAP_{uuid.uuid4().hex[:16].upper()}",
            platform=platform,
            captured_at=moment,
            fields=fields,
            digest=profile_digest(fields),
        )
    except ValidationError:
        raise ContractValidationError(
            "The profile sections are invalid (each name once)."
        ) from None


def _current(
    store: SqliteEvalsRepository, platforms: list[str]
) -> dict[str, tuple[ProfileVersion, ProfileSnapshot]]:
    current = {}
    for platform in platforms:
        live = store.latest_profile(platform)
        if live is not None:
            current[platform] = live
    return current


def _proposal(store: SqliteEvalsRepository, proposal_id: str) -> ProfileProposal:
    proposal = store.get_profile_proposal(proposal_id)
    if proposal is None:
        raise ContractValidationError(
            "Profile proposal was not found.", details={"proposal_id": proposal_id}
        )
    return proposal


def _platforms(proposal: ProfileProposal) -> list[str]:
    return [target.platform for target in proposal.targets]


@profile_app.command("snapshot")
def snapshot(
    fields_path: Annotated[
        Path, typer.Argument(help="JSON list of {name, text}: the profile sections as read.")
    ],
    platform: Annotated[str, typer.Option("--platform")],
    database: DatabaseOption = DEFAULT_DATABASE,
    now: Annotated[
        str | None, typer.Option("--now", help="ISO time it was read; defaults to now.")
    ] = None,
) -> None:
    """Keep one board's profile as read, and open a version if its words changed."""
    try:
        current = _read_snapshot(fields_path, platform, _now(now))
        store = _store(database)
        live = store.latest_profile(platform)
        store.save_profile_snapshot(current)
        version = next_profile_version(
            live[0] if live else None, live[1] if live else None, current
        )
        if version is not None:
            store.save_profile_version(version)
        _emit(
            {
                "snapshot_id": current.snapshot_id,
                "digest": current.digest,
                "sections": [field.name for field in current.fields],
                "version": version.model_dump(mode="json") if version is not None else None,
            }
        )
    except (JobAgentError, ValueError) as error:
        _fail(error if isinstance(error, JobAgentError) else ContractValidationError(str(error)))


@profile_app.command("versions")
def versions(
    platform: Annotated[str, typer.Option("--platform")],
    database: DatabaseOption = DEFAULT_DATABASE,
) -> None:
    """List a board's profile versions, oldest first. Sections are named, not quoted."""
    try:
        _emit([v.model_dump(mode="json") for v in _store(database).profile_versions(platform)])
    except JobAgentError as error:
        _fail(error)


@profile_app.command("propose")
def propose(
    proposal_path: Annotated[Path, typer.Argument(help="ProfileProposalDraft JSON.")],
    candidate: Annotated[str, typer.Option("--candidate", help="Whose confirmed evidence.")],
    database: DatabaseOption = DEFAULT_DATABASE,
) -> None:
    """Check a profile change against the live versions and the rules; store it."""
    try:
        try:
            draft = ProfileProposalDraft.model_validate_json(proposal_path.read_bytes())
        except (OSError, ValidationError):
            raise ContractValidationError(
                "The proposal file is not a valid profile proposal.",
                details={"file_name": proposal_path.name},
            ) from None
        store = _store(database)
        platforms = [target.platform for target in draft.targets]
        registry = SourceRegistry.default()
        specs = {
            platform: registry.get(platform).profile if platform in registry.ids() else None
            for platform in platforms
        }
        evidence = SqliteCandidateRepository(store.database).list_evidence(candidate)
        proposal = FLYWHEEL.propose(
            draft,
            current=_current(store, platforms),
            specs=specs,
            confirmed_evidence_ids={item.id for item in evidence if item.user_confirmed},
            proposal_id=f"PROFPROP_{uuid.uuid4().hex[:16].upper()}",
            created_at=datetime.now(UTC),
        )
        store.save_profile_proposal(proposal)
        _emit(
            {
                "proposal_id": proposal.proposal_id,
                "proposal_digest": proposal.proposal_digest,
                "expected_digests": proposal.expected_digests,
                "sections": {
                    target.platform: [change.name for change in target.changes]
                    for target in proposal.targets
                },
            }
        )
    except JobAgentError as error:
        _fail(error)


@profile_app.command("ask")
def ask(proposal_id: str, database: DatabaseOption = DEFAULT_DATABASE) -> None:
    """Put every change to the person, old and new word for word. This approves nothing."""
    try:
        store = _store(database)
        proposal = _proposal(store, proposal_id)
        question = FLYWHEEL.ask(
            proposal, current=_current(store, _platforms(proposal)), asked_at=datetime.now(UTC)
        )
        store.save_profile_ask(question)
        _emit(question.model_dump(mode="json"))
    except JobAgentError as error:
        _fail(error)


@profile_app.command("approve")
def approve(
    proposal_id: str,
    request: Annotated[str, typer.Option("--request", help="The PROFASK_* put first.")],
    answer: Annotated[str, typer.Option("--answer", help="The person's own words, verbatim.")],
    database: DatabaseOption = DEFAULT_DATABASE,
) -> None:
    """Record the person's approval of exactly this proposal."""
    try:
        store = _store(database)
        proposal = _proposal(store, proposal_id)
        question = store.get_profile_ask(request)
        if question is None:
            raise ApprovalRequiredError(
                "An approval must answer a question that was posed first.",
                details={"proposal_id": proposal_id, "ask_id": request},
            )
        approval = FLYWHEEL.approve(
            proposal,
            question,
            answer=answer,
            current=_current(store, _platforms(proposal)),
            approved_at=datetime.now(UTC),
        )
        store.save_profile_approval(approval)
        _emit(approval.model_dump(mode="json"))
    except JobAgentError as error:
        _fail(error)


@profile_app.command("gate")
def gate(
    proposal_id: str,
    platform: Annotated[str, typer.Option("--platform")],
    database: DatabaseOption = DEFAULT_DATABASE,
) -> None:
    """Say whether this board may be edited now, and hand over the exact approved words."""
    try:
        store = _store(database)
        proposal = _proposal(store, proposal_id)
        decision = FLYWHEEL.gate(
            proposal,
            store.get_profile_approval(proposal_id),
            platform,
            current=_current(store, _platforms(proposal)),
            applications=store.profile_applications(proposal_id),
        )
        _emit(decision.model_dump(mode="json"))
    except JobAgentError as error:
        _fail(error)


@profile_app.command("record")
def record(
    proposal_id: str,
    platform: Annotated[str, typer.Option("--platform")],
    result: Annotated[ProfileApplyResult, typer.Option("--result")],
    readback: Annotated[
        Path | None, typer.Option("--readback", help="Sections read back after saving.")
    ] = None,
    reason: Annotated[str | None, typer.Option("--reason")] = None,
    database: DatabaseOption = DEFAULT_DATABASE,
    now: Annotated[str | None, typer.Option("--now")] = None,
) -> None:
    """Record one attempt. `applied` stands only if the read-back is the approved profile."""
    try:
        moment = _now(now)
        store = _store(database)
        proposal = _proposal(store, proposal_id)
        approval = store.get_profile_approval(proposal_id)
        decision = FLYWHEEL.gate(
            proposal,
            approval,
            platform,
            current=_current(store, _platforms(proposal)),
            applications=store.profile_applications(proposal_id),
        )
        if not decision.allowed or approval is None:
            raise ContractValidationError(
                "This board cannot be recorded for this proposal.",
                details={"proposal_id": proposal_id, "reason": decision.reason},
            )
        snapshot = _read_snapshot(readback, platform, moment) if readback is not None else None
        application, version = FLYWHEEL.record(
            proposal,
            approval,
            platform,
            result,
            readback=snapshot,
            current=_current(store, [platform]),
            recorded_at=moment,
            reason=reason,
        )
        if snapshot is not None:
            store.save_profile_snapshot(snapshot)
        if version is not None:
            store.save_profile_version(version)
        store.save_profile_application(application)
        _emit(
            {
                "application": application.model_dump(mode="json"),
                "version": version.model_dump(mode="json") if version is not None else None,
            }
        )
    except (JobAgentError, ValueError) as error:
        _fail(error if isinstance(error, JobAgentError) else ContractValidationError(str(error)))
