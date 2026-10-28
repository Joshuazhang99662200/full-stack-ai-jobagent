"""Atomic append-only tracking history with candidate scope and event replay."""

import sqlite3
from datetime import datetime

from jobagent.errors import ContractValidationError, StorageError
from jobagent.jobs.jd_snapshot import canonical_digest
from jobagent.jobs.sent_tracking import advance, start_tracking
from jobagent.schemas.conversation import Conversation, ConversationEvent
from jobagent.schemas.sent_tracking import (
    SentProof,
    SentTrackingRecord,
    TrackingEventInput,
    TrackingHistoryEvent,
    TrackingState,
)
from jobagent.storage.database import Database


class SqliteSentTrackingRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _current(
        connection: sqlite3.Connection, tracking_id: str, candidate_id: str
    ) -> SentTrackingRecord:
        row = connection.execute(
            "SELECT e.event_json FROM sent_tracking_events e "
            "JOIN sent_tracking_roots r ON r.tracking_id = e.tracking_id "
            "WHERE e.tracking_id = ? AND r.candidate_id = ? ORDER BY e.version DESC LIMIT 1",
            (tracking_id, candidate_id),
        ).fetchone()
        if row is None:
            raise ContractValidationError("Tracking record not found for this candidate.")
        return TrackingHistoryEvent.model_validate_json(row["event_json"]).state

    @staticmethod
    def _append(connection: sqlite3.Connection, events: list[TrackingHistoryEvent]) -> None:
        for event in events:
            connection.execute(
                "INSERT INTO sent_tracking_events VALUES (?, ?, ?, ?)",
                (event.event_id, event.tracking_id, event.version, event.model_dump_json()),
            )

    def get(self, tracking_id: str, candidate_id: str) -> SentTrackingRecord:
        with self.database.connect() as connection:
            return self._current(connection, tracking_id, candidate_id)

    def start(
        self,
        proof: SentProof,
        *,
        candidate_id: str,
        tracking_id: str,
        now: datetime,
        next_poll_at: datetime | None = None,
    ) -> SentTrackingRecord:
        digest = canonical_digest(
            [candidate_id, tracking_id, proof.model_dump(mode="json")]
            + ([next_poll_at.isoformat()] if next_poll_at else [])
        )
        try:
            with self.database.connect() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                old = connection.execute(
                    "SELECT creation_digest FROM sent_tracking_roots WHERE tracking_id = ?",
                    (tracking_id,),
                ).fetchone()
                if old is not None:
                    if old["creation_digest"] != digest:
                        raise ContractValidationError("Tracking ID has a different send proof.")
                    return self._current(connection, tracking_id, candidate_id)
                if (
                    connection.execute(
                        "SELECT 1 FROM sent_tracking_sends WHERE send_reference = ?",
                        (proof.send_reference,),
                    ).fetchone()
                    is not None
                ):
                    raise ContractValidationError("This send already has a tracking record.")
                events = start_tracking(
                    proof,
                    candidate_id=candidate_id,
                    tracking_id=tracking_id,
                    now=now,
                    next_poll_at=next_poll_at,
                )
                connection.execute(
                    "INSERT INTO sent_tracking_roots VALUES (?, ?, ?)",
                    (tracking_id, candidate_id, digest),
                )
                connection.execute(
                    "INSERT INTO sent_tracking_sends VALUES (?, ?)",
                    (proof.send_reference, tracking_id),
                )
                self._append(connection, events)
                return events[-1].state
        except sqlite3.Error as error:
            raise StorageError("Tracking history unavailable.") from error

    def apply(
        self,
        event: TrackingEventInput,
        *,
        now: datetime,
        conversation: Conversation | None = None,
        inbound: ConversationEvent | None = None,
        reply_proof: SentProof | None = None,
    ) -> SentTrackingRecord:
        digest = canonical_digest(event.model_dump(mode="json"))
        try:
            with self.database.connect() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                state = self._current(connection, event.tracking_id, event.candidate_id)
                old = connection.execute(
                    "SELECT * FROM sent_tracking_requests WHERE event_id = ?",
                    (event.event_id,),
                ).fetchone()
                if old is not None:
                    if old["input_digest"] != digest or old["tracking_id"] != event.tracking_id:
                        raise ContractValidationError("Event ID has different content.")
                    return SentTrackingRecord.model_validate_json(old["response_json"])
                events = advance(
                    state,
                    event,
                    now=now,
                    conversation=conversation,
                    inbound=inbound,
                    reply_proof=reply_proof,
                )
                if reply_proof is not None:
                    if (
                        connection.execute(
                            "SELECT 1 FROM sent_tracking_sends WHERE send_reference = ?",
                            (reply_proof.send_reference,),
                        ).fetchone()
                        is not None
                    ):
                        raise ContractValidationError(
                            "This approved-send proof was already tracked."
                        )
                    connection.execute(
                        "INSERT INTO sent_tracking_sends VALUES (?, ?)",
                        (reply_proof.send_reference, event.tracking_id),
                    )
                self._append(connection, events)
                result = events[-1].state
                connection.execute(
                    "INSERT INTO sent_tracking_requests VALUES (?, ?, ?, ?)",
                    (event.event_id, event.tracking_id, digest, result.model_dump_json()),
                )
                return result
        except sqlite3.Error as error:
            raise StorageError("Tracking history unavailable.") from error

    def history(self, tracking_id: str, candidate_id: str) -> list[TrackingHistoryEvent]:
        with self.database.connect() as connection:
            self._current(connection, tracking_id, candidate_id)
            rows = connection.execute(
                "SELECT event_json FROM sent_tracking_events "
                "WHERE tracking_id = ? ORDER BY version",
                (tracking_id,),
            ).fetchall()
        return [TrackingHistoryEvent.model_validate_json(row["event_json"]) for row in rows]

    def list_records(self, candidate_id: str) -> list[SentTrackingRecord]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT tracking_id FROM sent_tracking_roots WHERE candidate_id = ? "
                "ORDER BY tracking_id",
                (candidate_id,),
            ).fetchall()
            return [self._current(connection, row["tracking_id"], candidate_id) for row in rows]

    def due(self, candidate_id: str, *, now: datetime) -> list[SentTrackingRecord]:
        return [
            state
            for state in self.list_records(candidate_id)
            if state.tracking_state == TrackingState.AWAITING_REPLY
            and not state.paused
            and state.next_check_at is not None
            and state.next_check_at <= now
        ]
