"""Immutable owner feedback with its provenance, and versioned sourcing plans."""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from pydantic import ValidationError

from jobagent.errors import ContractValidationError, StorageError
from jobagent.outreach.feedback import build_outreach_feedback
from jobagent.schemas.candidate import CandidateProfile, EvidenceItem
from jobagent.schemas.jobs import NormalizedJob
from jobagent.schemas.outreach import OutreachApproval, OutreachAsk, OutreachBatch, OutreachItem
from jobagent.schemas.sourcing_feedback import (
    FeedbackSearchStrategy,
    OutreachFeedbackLink,
    OutreachFeedbackOutcome,
    OutreachFeedbackReceipt,
    OutreachFeedbackRequest,
    PagedCardState,
    SourcingFeedback,
)
from jobagent.storage.database import Database

_DECISION = {"approve": "approved", "revise": "revision_requested", "decline": "declined"}


@dataclass(frozen=True)
class BoundFeedback:
    """A stored feedback event with the asked list and words it is bound to.

    `choices` lists the (item, words, recorded decision) candidates the event may
    judge; readers still verify job, ownership and digests against them.
    """

    event: SourcingFeedback
    batch: OutreachBatch
    ask: OutreachAsk
    owner_id: str | None
    demo_mode: bool
    valid_until: datetime | None
    choices: tuple[tuple[OutreachItem, str, str | None], ...]


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def bound_feedback(connection: sqlite3.Connection) -> list[BoundFeedback]:
    """Read feedback whose provenance is intact, oldest first; never writes.

    Two provenances exist: approval cards from older hosts, and host-neutral links
    to one asked item. Events with neither, or with mismatched columns, are skipped.
    """
    tables = _tables(connection)
    base = {"sourcing_feedback_events", "outreach_batches", "outreach_asks"}
    if not base <= tables:
        return []
    result: list[BoundFeedback] = []
    if {"paged_card_events", "paged_card_states"} <= tables:
        for row in connection.execute(
            "SELECT f.event_id,f.idempotency_key,f.source,f.occurred_at,f.event_json,"
            "e.message_id,s.state_json,b.batch_json,q.ask_json "
            "FROM sourcing_feedback_events f "
            "JOIN paged_card_events e ON e.event_id=f.event_id "
            "JOIN paged_card_states s ON s.message_id=e.message_id "
            "JOIN outreach_batches b ON b.batch_id=json_extract(s.state_json,'$.batch_id') "
            "JOIN outreach_asks q ON q.ask_id=json_extract(s.state_json,'$.ask_id')"
        ):
            try:
                event = SourcingFeedback.model_validate_json(row[4])
                state = PagedCardState.model_validate_json(row[6])
                batch = OutreachBatch.model_validate_json(row[7])
                ask = OutreachAsk.model_validate_json(row[8])
                if not _columns_match(event, row) or state.message_id != row[5] or (
                    state.batch_id != batch.batch_id or state.ask_id != ask.ask_id
                ):
                    continue
            except (ValidationError, ValueError):
                continue
            result.append(BoundFeedback(
                event=event, batch=batch, ask=ask, owner_id=state.candidate_id,
                demo_mode=state.demo_mode, valid_until=state.expires_at,
                choices=tuple(
                    (item, state.drafts.get(str(item.number), item.text),
                     state.decisions.get(str(item.number)))
                    for item in batch.items
                ),
            ))
    if "outreach_feedback_links" in tables:
        for row in connection.execute(
            "SELECT f.event_id,f.idempotency_key,f.source,f.occurred_at,f.event_json,"
            "l.link_json,b.batch_json,q.ask_json "
            "FROM sourcing_feedback_events f "
            "JOIN outreach_feedback_links l ON l.event_id=f.event_id "
            "JOIN outreach_batches b ON b.batch_id=l.batch_id "
            "JOIN outreach_asks q ON q.ask_id=l.ask_id"
        ):
            try:
                event = SourcingFeedback.model_validate_json(row[4])
                link = OutreachFeedbackLink.model_validate_json(row[5])
                batch = OutreachBatch.model_validate_json(row[6])
                ask = OutreachAsk.model_validate_json(row[7])
                if not _columns_match(event, row) or link.event_id != event.event_id or (
                    link.batch_id != batch.batch_id or link.ask_id != ask.ask_id
                ):
                    continue
            except (ValidationError, ValueError):
                continue
            items = [item for item in batch.items if item.number == link.item_number]
            result.append(BoundFeedback(
                event=event, batch=batch, ask=ask, owner_id=event.candidate_id,
                demo_mode=False, valid_until=None,
                choices=tuple((item, link.words, _DECISION[event.action]) for item in items),
            ))
    result.sort(key=lambda bound: (bound.event.occurred_at, bound.event.event_id))
    return result


def _columns_match(event: SourcingFeedback, row: sqlite3.Row | tuple[object, ...]) -> bool:
    return (
        event.event_id == row[0]
        and event.idempotency_key == row[1]
        and event.source == row[2]
        and event.occurred_at == datetime.fromisoformat(str(row[3]))
    )


class SqliteFeedbackRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def state(self, message_id: str) -> PagedCardState | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT state_json FROM paged_card_states WHERE message_id = ?", (message_id,),
            ).fetchone()
        return PagedCardState.model_validate_json(row[0]) if row else None

    def register(self, state: PagedCardState) -> None:
        with self.database.connect() as connection, connection:
            connection.execute(
                "INSERT INTO paged_card_states VALUES (?, ?, ?)",
                (state.message_id, state.revision, state.model_dump_json()),
            )

    def commit(
        self, state: PagedCardState, *, expected_revision: int, event_id: str, now: datetime,
        feedback: SourcingFeedback | None = None,
        approval_bundle: tuple[OutreachBatch, OutreachAsk, OutreachApproval] | None = None,
        withdraw_parent: bool = False,
    ) -> str:
        """Atomically persist the one decision, its exact approval and dedup key."""
        try:
            with self.database.transaction() as connection:
                if connection.execute(
                    "SELECT 1 FROM paged_card_events WHERE event_id = ?", (event_id,),
                ).fetchone():
                    return "duplicate"
                cursor = connection.execute(
                    "UPDATE paged_card_states SET revision = ?, state_json = ? "
                    "WHERE message_id = ? AND revision = ?",
                    (state.revision, state.model_dump_json(), state.message_id, expected_revision),
                )
                if cursor.rowcount != 1:
                    return "stale"
                if approval_bundle:
                    batch, ask, approval = approval_bundle
                    connection.execute("INSERT INTO outreach_batches VALUES (?, ?, ?)",
                                       (batch.batch_id, batch.model_dump_json(), now.isoformat()))
                    connection.execute("INSERT INTO outreach_asks VALUES (?, ?, ?)",
                                       (ask.ask_id, ask.batch_id, ask.model_dump_json()))
                    connection.execute("INSERT INTO outreach_approvals VALUES (?, ?, ?)",
                                       (approval.approval_id, approval.batch_id,
                                        approval.model_dump_json()))
                if feedback:
                    connection.execute(
                        "INSERT INTO sourcing_feedback_events VALUES (?, ?, ?, ?, ?)",
                        (feedback.event_id, feedback.idempotency_key, feedback.source,
                         feedback.model_dump_json(), feedback.occurred_at.isoformat()),
                    )
                if withdraw_parent:
                    connection.execute(
                        "INSERT INTO outreach_withdrawals VALUES (?, ?, ?)",
                        (state.batch_id, "All listed items were decided individually.",
                         now.isoformat()),
                    )
                connection.execute("INSERT INTO paged_card_events VALUES (?, ?, ?)",
                                   (event_id, state.message_id, now.isoformat()))
            return "stored"
        except sqlite3.Error as error:
            raise StorageError("Could not persist paged approval.") from error

    def decided_numbers(self, batch_id: str) -> set[int]:
        """Items of a list that some front end already decided one by one."""
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT state_json FROM paged_card_states "
                "WHERE json_extract(state_json, '$.batch_id') = ?",
                (batch_id,),
            ).fetchall()
        return {
            int(number)
            for row in rows
            for number in PagedCardState.model_validate_json(row[0]).decisions
        }

    def event_seen(self, event_id: str) -> bool:
        with self.database.connect() as connection:
            return connection.execute(
                "SELECT 1 FROM paged_card_events WHERE event_id = ?", (event_id,),
            ).fetchone() is not None

    def events(self) -> list[SourcingFeedback]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT event_json FROM sourcing_feedback_events ORDER BY occurred_at, event_id",
            ).fetchall()
        return [SourcingFeedback.model_validate_json(row[0]) for row in rows]

    def save_strategy(self, strategy: FeedbackSearchStrategy) -> None:
        with self.database.transaction() as connection:
            scope = json.dumps([strategy.candidate_id, strategy.actor_id, strategy.source])
            head = connection.execute(
                "SELECT version FROM feedback_strategy_heads WHERE scope_key = ?", (scope,),
            ).fetchone()
            if head and head[0] not in {strategy.previous_version, strategy.version}:
                raise ContractValidationError("Feedback strategy parent is stale.")
            connection.execute(
                "INSERT OR IGNORE INTO sourcing_feedback_strategies VALUES (?, ?, ?)",
                (strategy.version, strategy.source, strategy.model_dump_json()),
            )
            for event_id in strategy.observed_feedback_ids:
                connection.execute(
                    "INSERT OR IGNORE INTO feedback_consumptions VALUES (?, ?, ?)",
                    (scope, event_id, strategy.version),
                )
            connection.execute(
                "INSERT INTO feedback_strategy_heads VALUES (?, ?) "
                "ON CONFLICT(scope_key) DO UPDATE SET version = excluded.version",
                (scope, strategy.version),
            )

    def record_outreach_feedback(
        self, request: OutreachFeedbackRequest
    ) -> OutreachFeedbackReceipt:
        """Append the person's per-item decisions atomically; replays are no-ops."""
        try:
            with self.database.transaction() as connection:
                batch, ask, approval, jobs, owned = _feedback_context(connection, request)
                records = build_outreach_feedback(
                    request, batch=batch, ask=ask, approval=approval, jobs=jobs,
                    owned_evidence_ids=owned,
                )
                outcomes = []
                for event, link in records:
                    stored = connection.execute(
                        "SELECT f.event_json, l.link_json FROM outreach_feedback_links l "
                        "JOIN sourcing_feedback_events f ON f.event_id = l.event_id "
                        "WHERE l.event_id = ?",
                        (event.event_id,),
                    ).fetchone()
                    if stored is not None:
                        if (
                            SourcingFeedback.model_validate_json(stored[0]) != event
                            or OutreachFeedbackLink.model_validate_json(stored[1]) != link
                        ):
                            raise ContractValidationError(
                                "This item already has a recorded decision.",
                                details={"number": link.item_number},
                            )
                        outcomes.append(OutreachFeedbackOutcome(
                            number=link.item_number, event_id=event.event_id, status="duplicate"
                        ))
                        continue
                    connection.execute(
                        "INSERT INTO sourcing_feedback_events VALUES (?, ?, ?, ?, ?)",
                        (event.event_id, event.idempotency_key, event.source,
                         event.model_dump_json(), event.occurred_at.isoformat()),
                    )
                    connection.execute(
                        "INSERT INTO outreach_feedback_links VALUES (?, ?, ?, ?, ?, ?)",
                        (link.event_id, link.batch_id, link.ask_id, link.item_number,
                         link.model_dump_json(), event.occurred_at.isoformat()),
                    )
                    outcomes.append(OutreachFeedbackOutcome(
                        number=link.item_number, event_id=event.event_id, status="stored"
                    ))
        except sqlite3.Error as error:
            raise StorageError("Could not persist outreach feedback.") from error
        return OutreachFeedbackReceipt(
            batch_id=request.batch_id, ask_id=request.ask_id, items=outcomes
        )


def _feedback_context(
    connection: sqlite3.Connection, request: OutreachFeedbackRequest
) -> tuple[
    OutreachBatch, OutreachAsk, OutreachApproval | None, dict[str, NormalizedJob], set[str]
]:
    def one(sql: str, key: str) -> str | None:
        row = connection.execute(sql, (key,)).fetchone()
        return None if row is None else str(row[0])

    batch_json = one("SELECT batch_json FROM outreach_batches WHERE batch_id = ?", request.batch_id)
    ask_json = one("SELECT ask_json FROM outreach_asks WHERE ask_id = ?", request.ask_id)
    if batch_json is None or ask_json is None:
        raise ContractValidationError("Feedback must answer a stored list and question.")
    profile = one(
        "SELECT profile_json FROM candidate_profiles WHERE candidate_id = ?", request.candidate_id
    )
    if profile is None or CandidateProfile.model_validate_json(profile).id != request.candidate_id:
        raise ContractValidationError("The feedback candidate does not exist.")
    approval_json = one(
        "SELECT approval_json FROM outreach_approvals WHERE batch_id = ?", request.batch_id
    )
    batch = OutreachBatch.model_validate_json(batch_json)
    evidence = (
        EvidenceItem.model_validate_json(row[0])
        for row in connection.execute(
            "SELECT evidence_json FROM evidence_items WHERE candidate_id = ?",
            (request.candidate_id,),
        )
    )
    jobs = {}
    for item in batch.items:
        job_json = one("SELECT job_json FROM normalized_jobs WHERE job_id = ?", item.job_id)
        if job_json is not None:
            jobs[item.job_id] = NormalizedJob.model_validate_json(job_json)
    owned = {e.id for e in evidence if e.user_confirmed and e.confidence.value != "weak"}
    if not any(set(item.evidence_ids) <= owned and item.evidence_ids for item in batch.items):
        raise ContractValidationError("The asked list does not belong to this candidate.")
    approval = (
        None if approval_json is None else OutreachApproval.model_validate_json(approval_json)
    )
    return batch, OutreachAsk.model_validate_json(ask_json), approval, jobs, owned
