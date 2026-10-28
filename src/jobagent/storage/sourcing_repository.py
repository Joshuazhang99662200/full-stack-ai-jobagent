"""Atomic, append-only metering for host search and detail reads."""
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, time, timedelta

from jobagent.errors import ContractValidationError, StorageError
from jobagent.jobs.sourcing import SOURCING_DAY, refusal_reason
from jobagent.schemas.jobs import NormalizedJob
from jobagent.schemas.sourcing import (
    SourcingAttempt,
    SourcingAttemptRequest,
    SourcingBudget,
    SourcingPermit,
    SourcingRefusal,
    SourcingResult,
    SourcingResultRequest,
    SourcingRun,
    SourcingRunRequest,
)
from jobagent.storage.database import Database


def _bounds(now: datetime) -> tuple[str, str]:
    if now.tzinfo is None:
        raise ContractValidationError("A timezone-aware program clock is required.")
    day = now.astimezone(SOURCING_DAY).date()
    start = datetime.combine(day, time(), tzinfo=SOURCING_DAY)
    end = start + timedelta(days=1)
    return start.astimezone(UTC).isoformat(), end.astimezone(UTC).isoformat()


def _same_request(request: SourcingRunRequest | SourcingAttemptRequest | SourcingResultRequest,
                  stored: SourcingRun | SourcingAttempt | SourcingResult) -> bool:
    return request.model_dump() == stored.model_dump(include=set(type(request).model_fields))


class SqliteSourcingRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        try:
            with self.database.connect() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
        except sqlite3.Error as error:
            raise StorageError("Sourcing ledger unavailable.") from error

    @staticmethod
    def _get_run(connection: sqlite3.Connection, run_id: str) -> SourcingRun:
        row = connection.execute(
            "SELECT run_json FROM sourcing_runs WHERE run_id = ?", (run_id,),
        ).fetchone()
        if row is None:
            raise ContractValidationError("Unknown sourcing run.")
        return SourcingRun.model_validate_json(row["run_json"])

    def get_run(self, run_id: str) -> SourcingRun:
        with self.database.connect() as connection:
            return self._get_run(connection, run_id)

    def start_run(self, request: SourcingRunRequest, *, now: datetime,
                  daily_cap: int) -> SourcingRun:
        _bounds(now)
        run = SourcingRun(
            **request.model_dump(exclude={"schema_version"}),
            opened_at=now.astimezone(UTC), daily_detail_limit=daily_cap,
        )
        with self._write() as connection:
            self._capture_legacy(connection, request.source, now)
            row = connection.execute(
                "SELECT run_json FROM sourcing_runs WHERE run_id = ?", (request.run_id,),
            ).fetchone()
            if row is not None:
                old = SourcingRun.model_validate_json(row["run_json"])
                if not _same_request(request, old) or old.daily_detail_limit != daily_cap:
                    raise ContractValidationError("A run ID cannot change its frozen budget.")
                return old
            connection.execute(
                "INSERT INTO sourcing_runs (run_id, source, run_json) VALUES (?, ?, ?)",
                (run.run_id, run.source, run.model_dump_json()),
            )
        return run

    @staticmethod
    def _budget(connection: sqlite3.Connection, source: str, daily_cap: int,
                now: datetime) -> SourcingBudget:
        start, end = _bounds(now)
        attempts = [
            SourcingAttempt.model_validate_json(row["attempt_json"])
            for row in connection.execute(
                "SELECT attempt_json FROM sourcing_attempts "
                "WHERE source = ? AND occurred_at >= ? AND occurred_at < ?",
                (source, start, end),
            ).fetchall()
        ]
        details = [item for item in attempts if item.kind == "detail"]
        first_reads: dict[str, datetime] = {}
        for item in details:
            if item.source_job_id is not None:
                key = " ".join(item.source_job_id.split()).casefold()
                first_reads[key] = min(first_reads.get(key, item.occurred_at), item.occurred_at)
        # Old imports are a conservative observed-job estimate, never reconstructed
        # attempts. New attempts and their stored job must not consume twice.
        legacy_keys = {
            row["source_job_id"] for row in connection.execute(
                "SELECT source_job_id FROM sourcing_legacy_reads "
                "WHERE source = ? AND observed_day = ?",
                (source, now.astimezone(SOURCING_DAY).date().isoformat()),
            ).fetchall()
        }
        for row in connection.execute("SELECT job_json FROM normalized_jobs").fetchall():
            job = NormalizedJob.model_validate_json(row["job_json"])
            if (job.source == source
                    and job.collected_at.astimezone(SOURCING_DAY).date()
                    == now.astimezone(SOURCING_DAY).date()
                    and (
                        " ".join(job.source_job_id.split()).casefold() not in first_reads
                        or job.collected_at < first_reads[
                            " ".join(job.source_job_id.split()).casefold()
                        ]
                    )):
                legacy_keys.add(" ".join(job.source_job_id.split()).casefold())
        results = [
            SourcingResult.model_validate_json(row["result_json"])
            for row in connection.execute(
                "SELECT result_json FROM sourcing_results "
                "WHERE source = ? AND completed_at >= ? AND completed_at < ?",
                (source, start, end),
            ).fetchall()
        ]
        legacy = len(legacy_keys)
        used = len(details) + legacy
        return SourcingBudget(
            source=source, daily_cap=daily_cap, read_today=used,
            remaining=max(0, daily_cap-used), legacy_unmetered=legacy,
            query_attempts_today=sum(item.kind == "query" for item in attempts),
            listing_observations_today=sum(item.listing_count or 0 for item in results),
            halted=any(item.outcome == "gate" for item in results),
        )

    @staticmethod
    def _capture_legacy(connection: sqlite3.Connection, source: str, now: datetime) -> None:
        # Freeze observations made before metering, so a later save_job cannot
        # erase an already observed cost. Do not guess older repeated/failed reads.
        start, end = _bounds(now)
        first_reads: dict[str, datetime] = {}
        for row in connection.execute(
            "SELECT attempt_json FROM sourcing_attempts "
            "WHERE source = ? AND kind = 'detail' AND occurred_at >= ? AND occurred_at < ?",
            (source, start, end),
        ).fetchall():
            item = SourcingAttempt.model_validate_json(row["attempt_json"])
            if item.source_job_id is not None:
                key = " ".join(item.source_job_id.split()).casefold()
                first_reads[key] = min(first_reads.get(key, item.occurred_at), item.occurred_at)
        day = now.astimezone(SOURCING_DAY).date()
        for row in connection.execute("SELECT job_json FROM normalized_jobs").fetchall():
            job = NormalizedJob.model_validate_json(row["job_json"])
            key = " ".join(job.source_job_id.split()).casefold()
            if (job.source == source and job.collected_at.astimezone(SOURCING_DAY).date() == day
                    and (key not in first_reads or job.collected_at < first_reads[key])):
                connection.execute(
                    "INSERT OR IGNORE INTO sourcing_legacy_reads "
                    "(source, source_job_id, observed_day) VALUES (?, ?, ?)",
                    (source, key, day.isoformat()),
                )

    def budget(self, source: str, *, daily_cap: int, now: datetime) -> SourcingBudget:
        try:
            with self.database.connect() as connection:
                return self._budget(connection, source, daily_cap, now)
        except sqlite3.Error as error:
            raise StorageError("Sourcing budget unavailable.") from error

    def reserve(self, request: SourcingAttemptRequest, *, now: datetime) -> SourcingPermit:
        _bounds(now)
        with self._write() as connection:
            run = self._get_run(connection, request.run_id)
            self._capture_legacy(connection, run.source, now)
            budget = self._budget(connection, run.source, run.daily_detail_limit, now)
            rows = connection.execute(
                "SELECT kind, count(*) AS used FROM sourcing_attempts "
                "WHERE run_id = ? GROUP BY kind", (run.run_id,),
            ).fetchall()
            counts = {row["kind"]: row["used"] for row in rows}
            queries, details = counts.get("query", 0), counts.get("detail", 0)
            old = connection.execute(
                "SELECT attempt_json FROM sourcing_attempts WHERE attempt_id = ?",
                (request.attempt_id,),
            ).fetchone()
            previous = None if old is None else SourcingAttempt.model_validate_json(
                old["attempt_json"],
            )
            if previous is not None and not _same_request(request, previous):
                raise ContractValidationError("An attempt ID cannot change its target.")
            reason: SourcingRefusal | None = (
                "already_reserved" if previous is not None else refusal_reason(
                    request, run, budget, query_count=queries, detail_count=details, now=now,
                )
            )
            if reason is not None:
                return SourcingPermit(
                    allowed=False, reason=reason,
                    query_remaining=max(0, run.query_limit-queries),
                    detail_remaining=max(0, run.detail_limit-details),
                    budget=budget, attempt=previous,
                )
            attempt = SourcingAttempt(
                **request.model_dump(exclude={"schema_version"}),
                source=run.source, occurred_at=now.astimezone(UTC),
            )
            connection.execute(
                "INSERT INTO sourcing_attempts "
                "(attempt_id, run_id, source, kind, occurred_at, attempt_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (attempt.attempt_id, attempt.run_id, attempt.source, attempt.kind,
                 attempt.occurred_at.isoformat(), attempt.model_dump_json()),
            )
            budget = self._budget(connection, run.source, run.daily_detail_limit, now)
            return SourcingPermit(
                allowed=True, reason="allowed", attempt=attempt, budget=budget,
                query_remaining=max(0, run.query_limit-queries-(request.kind == "query")),
                detail_remaining=max(0, run.detail_limit-details-(request.kind == "detail")),
            )

    def complete(self, request: SourcingResultRequest, *, now: datetime) -> SourcingResult:
        _bounds(now)
        with self._write() as connection:
            row = connection.execute(
                "SELECT attempt_json FROM sourcing_attempts WHERE attempt_id = ?",
                (request.attempt_id,),
            ).fetchone()
            if row is None:
                raise ContractValidationError("A result needs an existing reserved attempt.")
            attempt = SourcingAttempt.model_validate_json(row["attempt_json"])
            if attempt.kind == "detail" and request.listing_count is not None:
                raise ContractValidationError("Detail results cannot claim listing observations.")
            if (attempt.kind == "query" and request.outcome == "complete"
                    and request.listing_count is None):
                raise ContractValidationError(
                    "Completed queries must record observed listing count."
                )
            old = connection.execute(
                "SELECT result_json FROM sourcing_results WHERE attempt_id = ?",
                (request.attempt_id,),
            ).fetchone()
            if old is not None:
                previous = SourcingResult.model_validate_json(old["result_json"])
                if not _same_request(request, previous):
                    raise ContractValidationError("An attempt result is immutable.")
                return previous
            result = SourcingResult(
                **request.model_dump(exclude={"schema_version"}),
                source=attempt.source, completed_at=now.astimezone(UTC),
            )
            connection.execute(
                "INSERT INTO sourcing_results "
                "(attempt_id, source, completed_at, result_json) VALUES (?, ?, ?, ?)",
                (result.attempt_id, result.source,
                 result.completed_at.isoformat(), result.model_dump_json()),
            )
            return result
