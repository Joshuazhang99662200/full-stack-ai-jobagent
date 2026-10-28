"""Observation-only sent tracking, backed by existing approval and audit records."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from jobagent.cli.private_io import fail, open_database, read_model
from jobagent.errors import ContractValidationError, JobAgentError
from jobagent.jobs.jd_snapshot import text_digest
from jobagent.jobs.sent_tracking import (
    outreach_proof,
    pending_execution,
    reply_proof,
    tracking_report,
)
from jobagent.schemas.sent_tracking import SentProof, TrackingEventInput, TrackingStartInput
from jobagent.storage.conversation_repository import SqliteConversationRepository
from jobagent.storage.database import Database
from jobagent.storage.jd_snapshot_repository import SqliteJDSnapshotRepository
from jobagent.storage.job_repository import SqliteJobRepository
from jobagent.storage.outreach_repository import SqliteOutreachRepository
from jobagent.storage.sent_tracking_repository import SqliteSentTrackingRepository

tracking_app = typer.Typer(help="Observe approved sends; never sends or approves messages.")
DatabaseOption = Annotated[Path, typer.Option("--database")]
CandidateOption = Annotated[str, typer.Option("--candidate")]


def _echo(value: object) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2))


def _reply(
    database: Database, conversation_id: str | None, result_id: str | None, readback: str | None
) -> SentProof:
    store = SqliteConversationRepository(database)
    conversation = store.get_conversation(conversation_id or "")
    if conversation is None or conversation.job_id is None or not result_id or readback is None:
        raise ContractValidationError("Existing bound conversation and reply result are required.")
    job = SqliteJobRepository(database).get_job(conversation.job_id)
    if job is None:
        raise ContractValidationError("The conversation has no cached job URL.")
    return reply_proof(
        conversation,
        store.list_events(conversation.conversation_id),
        result_id,
        readback,
        str(job.url),
    )


@tracking_app.command("start")
def start(path: Path, database: DatabaseOption = Path(".jobagent/jobagent.sqlite3")) -> None:
    try:
        request = read_model(path, TrackingStartInput)
        db = open_database(database)
        if request.audit_id is not None:
            store = SqliteOutreachRepository(db)
            audit = next((a for a in store.list_audits() if a.audit_id == request.audit_id), None)
            if audit is None:
                raise ContractValidationError("Existing send audit not found.")
            batch, approval = store.get_batch(audit.batch_id), store.get_approval(audit.batch_id)
            if batch is None or approval is None:
                raise ContractValidationError("Existing batch and approval are required.")
            proof = outreach_proof(batch, approval, audit, request.readback_text)
        else:
            proof = _reply(
                db, request.conversation_id, request.reply_result_event_id, request.readback_text
            )
        result = SqliteSentTrackingRepository(db).start(
            proof,
            candidate_id=request.candidate_id,
            tracking_id=request.tracking_id or "TRACK_" + text_digest(proof.send_reference)[7:31],
            now=datetime.now(UTC),
        )
        _echo(result.model_dump(mode="json"))
    except JobAgentError as error:
        fail(error)


@tracking_app.command("event")
def event(path: Path, database: DatabaseOption = Path(".jobagent/jobagent.sqlite3")) -> None:
    try:
        request = read_model(path, TrackingEventInput)
        db = open_database(database)
        store = SqliteSentTrackingRepository(db)
        store.get(request.tracking_id, request.candidate_id)
        conversations = SqliteConversationRepository(db)
        conversation = conversations.get_conversation(request.conversation_id or "")
        inbound = next(
            (
                e
                for e in conversations.list_events(request.conversation_id or "")
                if e.event_id == request.inbound_event_id
            ),
            None,
        )
        proof = None
        if request.kind == "reply_sent":
            try:
                proof = _reply(
                    db,
                    request.conversation_id,
                    request.reply_result_event_id,
                    request.readback_text,
                )
            except ContractValidationError as error:
                if error.details.get("reason") != "readback_mismatch":
                    raise
                anomaly = request.model_copy(
                    update={
                        "kind": "anomaly",
                        "evidence_kind": "send_audit",
                        "readback_text": None,
                    }
                )
                paused = store.apply(anomaly, now=datetime.now(UTC))
                raise ContractValidationError(
                    "Reply readback mismatch; tracking paused for owner review.",
                    details={
                        "reason": "readback_mismatch",
                        "paused": True,
                        "tracking_version": paused.tracking_version,
                    },
                ) from error
        result = store.apply(
            request,
            now=datetime.now(UTC),
            conversation=conversation,
            inbound=inbound,
            reply_proof=proof,
        )
        _echo(result.model_dump(mode="json"))
    except JobAgentError as error:
        fail(error)


@tracking_app.command("status")
def status(
    tracking_id: str,
    candidate: CandidateOption,
    database: DatabaseOption = Path(".jobagent/jobagent.sqlite3"),
) -> None:
    try:
        result = SqliteSentTrackingRepository(open_database(database)).get(tracking_id, candidate)
        _echo(result.model_dump(mode="json"))
    except JobAgentError as error:
        fail(error)


@tracking_app.command("history")
def history(
    tracking_id: str,
    candidate: CandidateOption,
    database: DatabaseOption = Path(".jobagent/jobagent.sqlite3"),
) -> None:
    try:
        result = SqliteSentTrackingRepository(open_database(database)).history(
            tracking_id, candidate
        )
        _echo([e.model_dump(mode="json") for e in result])
    except JobAgentError as error:
        fail(error)


@tracking_app.command("due")
def due(candidate_id: str, database: DatabaseOption = Path(".jobagent/jobagent.sqlite3")) -> None:
    try:
        result = SqliteSentTrackingRepository(open_database(database)).due(
            candidate_id,
            now=datetime.now(UTC),
        )
        _echo([s.model_dump(mode="json") for s in result])
    except JobAgentError as error:
        fail(error)


@tracking_app.command("report")
def report(
    candidate_id: str, database: DatabaseOption = Path(".jobagent/jobagent.sqlite3")
) -> None:
    try:
        db = open_database(database)
        _echo(
            tracking_report(
                SqliteSentTrackingRepository(db).list_records(candidate_id),
                SqliteJDSnapshotRepository(db).feature_sets(),
            )
        )
    except JobAgentError as error:
        fail(error)


@tracking_app.command("pending")
def pending(
    batch_id: str,
    session: Annotated[str, typer.Option("--session")],
    database: DatabaseOption = Path(".jobagent/jobagent.sqlite3"),
) -> None:
    try:
        store = SqliteOutreachRepository(open_database(database))
        batch, approval = store.get_batch(batch_id), store.get_approval(batch_id)
        if batch is None or approval is None or store.is_withdrawn(batch_id):
            raise ContractValidationError("An active approved batch is required.")
        now = datetime.now(UTC)
        leases = {
            item.platform: store.holds_lease(item.platform, session, now=now)
            for item in batch.items
        }
        _echo(pending_execution(batch, approval, store.list_audits(), lease_held=leases, now=now))
    except JobAgentError as error:
        fail(error)
