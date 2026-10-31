"""Immutable configured query receipts and one-time real-query claims."""

import sqlite3
from datetime import datetime

from jobagent.errors import ContractValidationError
from jobagent.jobs.jd_snapshot import canonical_digest
from jobagent.jobs.query_selection import select_query_results
from jobagent.jobs.sourcing import SOURCING_DAY
from jobagent.schemas.sourcing import (
    SourcingAttempt,
    SourcingQueryCapture,
    SourcingQuerySelection,
    SourcingResult,
)
from jobagent.storage.database import Database
from jobagent.storage.sourcing_repository import SqliteSourcingRepository


class SqliteQueryRepository:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.sourcing = SqliteSourcingRepository(database)

    def claim(
        self,
        attempt_id: str,
        *,
        run_id: str,
        source: str,
        query: str,
        request_digest: str,
        now: datetime,
    ) -> SourcingQuerySelection | None:
        with self.sourcing._write() as connection:
            run = self.sourcing._get_run(connection, run_id)
            self.sourcing._configured_request(connection, run, now=now)
            if run.top_per_query is None or run.rules_version is None:
                raise ContractValidationError("Real query requires a configured source round.")
            row = connection.execute(
                "SELECT attempt_json FROM sourcing_attempts WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()
            if row is None:
                raise ContractValidationError("A real query requires a reserved attempt.")
            attempt = SourcingAttempt.model_validate_json(row[0])
            if (
                attempt.run_id != run_id
                or attempt.kind != "query"
                or attempt.source != source
                or source != run.source
                or attempt.search_term != query
                or now < attempt.occurred_at
            ):
                raise ContractValidationError("Query does not match its actual reserved target.")
            old = connection.execute(
                "SELECT request_digest FROM sourcing_query_claims WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()
            if old:
                if old[0] != request_digest:
                    raise ContractValidationError("Query attempt already claimed different inputs.")
                saved = connection.execute(
                    "SELECT selection_json FROM sourcing_query_selections WHERE attempt_id = ?",
                    (attempt_id,),
                ).fetchone()
                if saved:
                    return SourcingQuerySelection.model_validate_json(saved[0])
                raise ContractValidationError(
                    "Query is already claimed with an unknown outcome; verification is required.",
                )
            if connection.execute(
                "SELECT 1 FROM sourcing_results WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone():
                raise ContractValidationError(
                    "Query already has a result; no new execution allowed."
                )
            budget = self.sourcing._budget(connection, run.source, run.daily_detail_limit, now)
            _, details = self.sourcing._round_counts(connection, run.run_id)
            if budget.remaining == 0 or details >= run.detail_limit:
                raise ContractValidationError("Query round/detail budget is exhausted.")
            if budget.halted or now.astimezone(SOURCING_DAY).date() != (
                attempt.occurred_at.astimezone(SOURCING_DAY).date()
            ):
                raise ContractValidationError(
                    "Query source is halted or its execution day expired."
                )
            connection.execute(
                "INSERT INTO sourcing_query_claims VALUES (?, ?, ?)",
                (attempt_id, request_digest, now.isoformat()),
            )
        return None

    def take(self, capture: SourcingQueryCapture, *, now: datetime) -> SourcingQuerySelection:
        with self.sourcing._write() as connection:
            return self.take_in(connection, capture, now=now)

    def take_in(
        self, connection: sqlite3.Connection, capture: SourcingQueryCapture, *, now: datetime,
    ) -> SourcingQuerySelection:
        """Record a real capture in the caller's existing atomic write transaction."""
        if not capture.loaded or capture.access_state not in {"public", "authenticated"}:
            raise ContractValidationError("Query results require an accessible loaded view.")
        digest = canonical_digest(capture.model_dump(mode="json"))
        old = connection.execute(
            "SELECT request_digest, selection_json FROM sourcing_query_selections "
            "WHERE attempt_id = ?",
            (capture.attempt_id,),
        ).fetchone()
        if old:
            if old[0] != digest:
                raise ContractValidationError("Query capture already contains different input.")
            return SourcingQuerySelection.model_validate_json(old[1])
        row = connection.execute(
            "SELECT attempt_json FROM sourcing_attempts WHERE attempt_id = ?",
            (capture.attempt_id,),
        ).fetchone()
        if row is None:
            raise ContractValidationError("Query capture needs a reserved attempt.")
        attempt = SourcingAttempt.model_validate_json(row[0])
        run = self.sourcing._get_run(connection, attempt.run_id)
        if attempt.kind != "query" or run.top_per_query is None or run.rules_version is None:
            raise ContractValidationError("Capture requires a configured query attempt.")
        if now.tzinfo is None or now < attempt.occurred_at:
            raise ContractValidationError("Capture cannot predate its actual reserved attempt.")
        seen = {
            row[0]
            for row in connection.execute(
                "SELECT source_job_id FROM sourcing_seen_listings WHERE run_id = ?",
                (run.run_id,),
            )
        }
        selected = select_query_results(
            capture.items,
            requested=run.top_per_query,
            source=run.source,
            seen=seen,
        )
        result = SourcingQuerySelection(
            **selected.model_dump(exclude={"schema_version"}),
            attempt_id=capture.attempt_id,
            run_id=run.run_id,
            source=run.source,
            rules_version=run.rules_version,
            next_cursor=capture.next_cursor,
        )
        outcome = SourcingResult(
            attempt_id=capture.attempt_id,
            outcome="complete",
            listing_count=result.taken_count,
            source=run.source,
            completed_at=now,
        )
        previous = connection.execute(
            "SELECT result_json FROM sourcing_results WHERE attempt_id = ?",
            (capture.attempt_id,),
        ).fetchone()
        if previous:
            prior = SourcingResult.model_validate_json(previous[0])
            if prior.outcome != "complete" or prior.listing_count != result.taken_count:
                raise ContractValidationError(
                    "Query result conflicts with the original receipt."
                )
        else:
            connection.execute(
                "INSERT INTO sourcing_results VALUES (?, ?, ?, ?)",
                (
                    outcome.attempt_id,
                    outcome.source,
                    outcome.completed_at.isoformat(),
                    outcome.model_dump_json(),
                ),
            )
        for item in result.items:
            connection.execute(
                "INSERT INTO sourcing_seen_listings VALUES (?, ?, ?)",
                (
                    run.run_id,
                    item.source_job_id,
                    capture.attempt_id,
                ),
            )
        connection.execute(
            "INSERT INTO sourcing_query_selections VALUES (?, ?, ?, ?)",
            (
                capture.attempt_id,
                run.run_id,
                digest,
                result.model_dump_json(),
            ),
        )
        return result
