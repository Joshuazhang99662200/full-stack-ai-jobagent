"""JSON-first commands for batch first-contact outreach.

`ask` never approves, `approve` never sends, and nothing here clicks anything: the
host sends in the person's own browser, one item at a time, after `next` says yes,
and reports each attempt with `record`. Every attempt leaves one immutable row.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Never
from uuid import uuid4

import typer
from pydantic import TypeAdapter, ValidationError

from jobagent.errors import ApprovalRequiredError, ContractValidationError, JobAgentError
from jobagent.evals.versioning import read_harness_version
from jobagent.jobs.preferences import preference_score
from jobagent.outreach.service import OutreachService, contacted_job_ids
from jobagent.schemas.common import ContractModel
from jobagent.schemas.job_intelligence import CandidateFilterContext
from jobagent.schemas.outreach import (
    OutreachApproval,
    OutreachAudit,
    OutreachBatch,
    OutreachDraft,
    OutreachResult,
)
from jobagent.skill_resources import default_skill_root
from jobagent.storage.candidate_repository import SqliteCandidateRepository
from jobagent.storage.database import Database
from jobagent.storage.evals_repository import SqliteEvalsRepository
from jobagent.storage.job_repository import SqliteJobRepository
from jobagent.storage.outreach_repository import SqliteOutreachRepository

DEFAULT_DATABASE = Path(".jobagent/jobagent.sqlite3")
DatabaseOption = Annotated[Path, typer.Option("--database", help="Local SQLite path.")]
SessionOption = Annotated[str, typer.Option("--session", help="The sending session's id.")]
LEASE_SECONDS = 1800

outreach_app = typer.Typer(
    help="List, ask, approve, then send first greetings one at a time under a lease.",
    no_args_is_help=True,
)


def _emit(value: ContractModel | dict[str, object]) -> None:
    if isinstance(value, ContractModel):
        typer.echo(value.model_dump_json(indent=2))
    else:
        typer.echo(json.dumps(value, ensure_ascii=False, indent=2))


def _fail(error: JobAgentError) -> Never:
    typer.echo(
        json.dumps(
            {"error": {"code": error.code, "message": error.message, "details": error.details}},
            ensure_ascii=False,
        )
    )
    raise typer.Exit(code=1)


def _database(path: Path) -> Database:
    path.parent.mkdir(parents=True, exist_ok=True)
    database = Database(path)
    database.migrate()
    return database


def _numbers(spec: str) -> list[int]:
    """Read "1-20,23" or "1、3" into item numbers."""
    numbers: list[int] = []
    try:
        for part in spec.replace("、", ",").replace("，", ",").split(","):  # noqa: RUF001
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                low, high = (int(value) for value in part.split("-", 1))
                numbers.extend(range(low, high + 1))
            else:
                numbers.append(int(part))
    except ValueError:
        raise ContractValidationError(
            "--items must list numbers such as 1-20,23.", details={"items": spec}
        ) from None
    return numbers


def _batch_and_approval(
    store: SqliteOutreachRepository, batch_id: str
) -> tuple[OutreachBatch, OutreachApproval]:
    batch = store.get_batch(batch_id)
    if batch is None:
        raise ContractValidationError(
            "Outreach batch was not found.", details={"batch_id": batch_id}
        )
    approval = store.get_approval(batch_id)
    if approval is None:
        raise ApprovalRequiredError(
            "No one has approved this batch yet.", details={"batch_id": batch_id}
        )
    return batch, approval


@outreach_app.command("draft-batch")
def draft_batch(
    drafts_path: Annotated[Path, typer.Argument(help="JSON list of OutreachDraft.")],
    database: DatabaseOption = DEFAULT_DATABASE,
    candidate: Annotated[
        str | None, typer.Option("--candidate", help="Whose confirmed evidence may be cited.")
    ] = None,
    filter_context: Annotated[
        Path | None,
        typer.Option("--filter-context", help="Preferences and the possible-match floor."),
    ] = None,
    hand_picked: Annotated[
        bool,
        typer.Option("--hand-picked", help="The person chose these jobs; tiers do not gate them."),
    ] = False,
) -> None:
    """Check host-drafted greetings and list the ones that pass as a numbered batch."""
    try:
        try:
            drafts = TypeAdapter(list[OutreachDraft]).validate_json(drafts_path.read_bytes())
        except (OSError, ValidationError):
            raise ContractValidationError(
                "The drafts file must hold a JSON list of drafts.",
                details={"file_name": drafts_path.name},
            ) from None
        db = _database(database)
        store = SqliteOutreachRepository(db)
        jobs = SqliteJobRepository(db)
        found = {draft.job_id: jobs.get_job(draft.job_id) for draft in drafts}
        confirmed: set[str] = set()
        tiers: dict[str, str] = {}
        if candidate is not None:
            evidence = SqliteCandidateRepository(db).list_evidence(candidate)
            confirmed = {item.id for item in evidence if item.user_confirmed}
            tiers = jobs.latest_match_tiers(candidate, [draft.job_id for draft in drafts])
        if hand_picked:
            tiers = {draft.job_id: "hand_picked" for draft in drafts}
        preferences: dict[str, float] = {}
        floor: float | None = None
        if filter_context is not None:
            context = CandidateFilterContext.model_validate_json(
                filter_context.read_text(encoding="utf-8")
            )
            floor = context.possible_match_min_preference
            for job_id, job in found.items():
                if job is not None:
                    preferences[job_id] = preference_score(
                        f"{job.title} {job.jd_raw}", context.preferred_factors
                    )[0]
        moment = datetime.now(UTC)
        version = read_harness_version(
            default_skill_root(),
            recorded_at=moment,
            extra=[filter_context] if filter_context is not None else [],
        )
        SqliteEvalsRepository(db).save_harness_version(version)
        report = OutreachService().build_batch(
            drafts,
            jobs={job_id: job for job_id, job in found.items() if job is not None},
            already_contacted=contacted_job_ids(store.list_audits()),
            confirmed_evidence_ids=confirmed,
            batch_id=f"OBATCH_{uuid4().hex[:16].upper()}",
            created_at=moment,
            match_tiers=tiers,
            preferences=preferences,
            possible_match_min_preference=floor,
            harness_version=version.version_id,
        )
        if report.batch is not None:
            store.save_batch(report.batch)
        _emit(report)
    except JobAgentError as error:
        _fail(error)


@outreach_app.command("ask")
def ask(batch_id: str, database: DatabaseOption = DEFAULT_DATABASE) -> None:
    """Put the numbered list to the person, word for word. This approves nothing."""
    try:
        store = SqliteOutreachRepository(_database(database))
        batch = store.get_batch(batch_id)
        if batch is None:
            raise ContractValidationError(
                "Outreach batch was not found.", details={"batch_id": batch_id}
            )
        question = OutreachService().ask(batch)
        store.save_ask(question)
        _emit(question)
    except JobAgentError as error:
        _fail(error)


@outreach_app.command("approve")
def approve(
    batch_id: str,
    request: Annotated[str, typer.Option("--request", help="The OASK_* that was put first.")],
    items: Annotated[str, typer.Option("--items", help="Numbers the person chose, e.g. 1-20,23.")],
    answer: Annotated[str, typer.Option("--answer", help="The person's own words, verbatim.")],
    database: DatabaseOption = DEFAULT_DATABASE,
) -> None:
    """Record the person's answer to a question that was asked about this batch."""
    try:
        store = SqliteOutreachRepository(_database(database))
        batch = store.get_batch(batch_id)
        if batch is None:
            raise ContractValidationError(
                "Outreach batch was not found.", details={"batch_id": batch_id}
            )
        if store.is_withdrawn(batch_id):
            raise ContractValidationError(
                "This batch was withdrawn and can no longer be approved.",
                details={"batch_id": batch_id},
            )
        approval = OutreachService().approve(
            batch, ask=store.get_ask(request), numbers=_numbers(items), attestation=answer
        )
        store.save_approval(approval)
        _emit(approval)
    except JobAgentError as error:
        _fail(error)


@outreach_app.command("withdraw")
def withdraw(
    batch_id: str,
    reason: Annotated[str, typer.Option("--reason", help="Why it will not be sent.")],
    database: DatabaseOption = DEFAULT_DATABASE,
) -> None:
    """Withdraw a batch nobody approved yet, so it is never approved or sent."""
    try:
        store = SqliteOutreachRepository(_database(database))
        if store.get_batch(batch_id) is None:
            raise ContractValidationError(
                "Outreach batch was not found.", details={"batch_id": batch_id}
            )
        if store.get_approval(batch_id) is not None:
            raise ContractValidationError(
                "This batch is already approved; close its items with "
                "`record --result withdrawn` instead.",
                details={"batch_id": batch_id},
            )
        if not reason.strip():
            raise ContractValidationError("A withdrawal needs a reason.")
        store.withdraw(batch_id, reason.strip(), datetime.now(UTC))
        _emit({"batch_id": batch_id, "withdrawn": True, "reason": reason.strip()})
    except JobAgentError as error:
        _fail(error)


@outreach_app.command("lease")
def lease(
    platform: str,
    session: SessionOption,
    database: DatabaseOption = DEFAULT_DATABASE,
    release: Annotated[bool, typer.Option("--release")] = False,
) -> None:
    """Take, renew or release the one sending lease a platform allows."""
    try:
        store = SqliteOutreachRepository(_database(database))
        if release:
            _emit({"platform": platform, "released": store.release_lease(platform, session)})
            return
        if not store.acquire_lease(
            platform, session, now=datetime.now(UTC), ttl_seconds=LEASE_SECONDS
        ):
            raise ContractValidationError(
                "Another session is sending on this platform.",
                details={"platform": platform, "reason": "lease_held_by_other_session"},
            )
        _emit({"platform": platform, "session": session, "ttl_seconds": LEASE_SECONDS})
    except JobAgentError as error:
        _fail(error)


@outreach_app.command("next")
def next_item(
    batch_id: str,
    platform: Annotated[str, typer.Option("--platform")],
    session: SessionOption,
    database: DatabaseOption = DEFAULT_DATABASE,
) -> None:
    """Say whether one more greeting may go out on this platform now, and which."""
    try:
        store = SqliteOutreachRepository(_database(database))
        batch, approval = _batch_and_approval(store, batch_id)
        now = datetime.now(UTC)
        held = store.holds_lease(platform, session, now=now)
        if held:
            store.acquire_lease(platform, session, now=now, ttl_seconds=LEASE_SECONDS)
        decision = OutreachService().next_item(
            batch, approval, platform=platform, audits=store.list_audits(), lease_held=held, now=now
        )
        _emit(decision)
    except JobAgentError as error:
        _fail(error)


@outreach_app.command("record")
def record(
    batch_id: str,
    number: int,
    result: Annotated[OutreachResult, typer.Option("--result")],
    session: SessionOption,
    database: DatabaseOption = DEFAULT_DATABASE,
    reason: Annotated[str | None, typer.Option("--reason")] = None,
) -> None:
    """Record what happened to one approved item. Once per item, never edited."""
    try:
        store = SqliteOutreachRepository(_database(database))
        batch, approval = _batch_and_approval(store, batch_id)
        items = {item.number: item for item in batch.items}
        if number not in approval.approved_numbers or number not in items:
            raise ApprovalRequiredError(
                "This item was not approved.", details={"batch_id": batch_id, "number": number}
            )
        item = items[number]
        now = datetime.now(UTC)
        if not store.holds_lease(item.platform, session, now=now):
            raise ContractValidationError(
                "Only the session holding the platform lease may record a send.",
                details={"platform": item.platform, "reason": "lease_not_held"},
            )
        if any(a.batch_id == batch_id and a.number == number for a in store.list_audits()):
            raise ContractValidationError(
                "This item already has a recorded result.",
                details={"batch_id": batch_id, "number": number},
            )
        audit = OutreachAudit(
            audit_id=f"OAUDIT_{uuid4().hex[:16].upper()}",
            batch_id=batch_id,
            number=number,
            job_id=item.job_id,
            platform=item.platform,
            item_digest=item.item_digest,
            approval_id=approval.approval_id,
            approval_channel=approval.channel,
            result=result,
            reason=reason,
            recorded_at=now,
        )
        store.append_audit(audit)
        _emit(audit)
    except JobAgentError as error:
        _fail(error)


@outreach_app.command("status")
def status(batch_id: str, database: DatabaseOption = DEFAULT_DATABASE) -> None:
    """Report each item's approval and recorded result."""
    try:
        store = SqliteOutreachRepository(_database(database))
        batch = store.get_batch(batch_id)
        if batch is None:
            raise ContractValidationError(
                "Outreach batch was not found.", details={"batch_id": batch_id}
            )
        approval = store.get_approval(batch_id)
        approved = set(approval.approved_numbers) if approval is not None else set()
        results = {a.number: a.result.value for a in store.list_audits() if a.batch_id == batch_id}
        _emit(
            {
                "batch_id": batch_id,
                "items": [
                    {
                        "number": item.number,
                        "platform": item.platform,
                        "company": item.company,
                        "title": item.title,
                        "approved": item.number in approved,
                        "result": results.get(item.number),
                    }
                    for item in batch.items
                ],
            }
        )
    except JobAgentError as error:
        _fail(error)
