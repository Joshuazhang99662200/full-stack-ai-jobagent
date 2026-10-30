"""Transactional card state, immutable feedback, and versioned sourcing plans."""

import json
import sqlite3
from datetime import datetime

from jobagent.errors import ContractValidationError, StorageError
from jobagent.schemas.outreach import OutreachApproval, OutreachAsk, OutreachBatch
from jobagent.schemas.sourcing_feedback import (
    FeedbackSearchStrategy,
    PagedCardState,
    SourcingFeedback,
)
from jobagent.storage.database import Database


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
            with self.database.connect() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
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
                        (state.batch_id, "All paged-card items were decided individually.",
                         now.isoformat()),
                    )
                connection.execute("INSERT INTO paged_card_events VALUES (?, ?, ?)",
                                   (event_id, state.message_id, now.isoformat()))
            return "stored"
        except sqlite3.Error as error:
            raise StorageError("Could not persist paged approval.") from error

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
        with self.database.connect() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
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
