"""Atomic, append-only metering for host search and detail reads."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, time, timedelta

from jobagent.errors import ContractValidationError, StorageError
from jobagent.harness.runtime import runtime_fingerprint
from jobagent.jobs.sourcing import SOURCING_DAY, refusal_reason
from jobagent.rules.bindings import bind_sourcing_run
from jobagent.rules.rounds import apply_round_overrides
from jobagent.rules.service import validate_snapshot
from jobagent.schemas.dynamic_rules import RuleProposal
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
from jobagent.storage.rule_repository import SqliteRuleRepository


def _bounds(now: datetime) -> tuple[str, str]:
    if now.tzinfo is None:
        raise ContractValidationError("A timezone-aware program clock is required.")
    day = now.astimezone(SOURCING_DAY).date()
    start = datetime.combine(day, time(), tzinfo=SOURCING_DAY)
    end = start + timedelta(days=1)
    return start.astimezone(UTC).isoformat(), end.astimezone(UTC).isoformat()


def _read_attempt_ids(connection: sqlite3.Connection, source: str, now: datetime) -> set[str]:
    return {
        row[0] for row in connection.execute(
            "SELECT attempt_id FROM sourcing_read_attempts WHERE source = ? AND platform_day = ?",
            (source, now.astimezone(SOURCING_DAY).date().isoformat()),
        )
    }


def _same_request(
    request: SourcingRunRequest | SourcingAttemptRequest | SourcingResultRequest,
    stored: SourcingRun | SourcingAttempt | SourcingResult,
) -> bool:
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
            "SELECT run_json FROM sourcing_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise ContractValidationError("Unknown sourcing run.")
        return SourcingRun.model_validate_json(row["run_json"])

    def get_run(self, run_id: str) -> SourcingRun:
        with self.database.connect() as connection:
            return self._get_run(connection, run_id)

    def start_run(
        self, request: SourcingRunRequest, *, now: datetime, daily_cap: int
    ) -> SourcingRun:
        _bounds(now)
        with self._write() as connection:
            request = self._configured_request(connection, request, now=now)
            return self._start_in(connection, request, now=now, daily_cap=daily_cap)

    def _start_in(
        self, connection: sqlite3.Connection, request: SourcingRunRequest,
        *, now: datetime, daily_cap: int,
    ) -> SourcingRun:
        expected_cap = request.daily_detail_cap or 50
        if not 1 <= daily_cap <= expected_cap or (
            (request.budget_profile == "muse-expanded-v1" or request.rules_version is not None)
            and daily_cap != expected_cap
        ):
            raise ContractValidationError("Program daily cap does not match the explicit policy.")
        run = SourcingRun(
            **request.model_dump(exclude={"schema_version"}),
            opened_at=now.astimezone(UTC),
            daily_detail_limit=daily_cap,
        )
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
        if request.round_overrides:
            from jobagent.storage.configuration_repository import consume_owner_change_request

            for override in request.round_overrides:
                consume_owner_change_request(connection, override.proposal, event_id=run.run_id)
        return run

    @staticmethod
    def _configured_request(
        connection: sqlite3.Connection, request: SourcingRunRequest,
        *, now: datetime,
    ) -> SourcingRunRequest:
        from jobagent.storage.configuration_repository import (
            configuration_initialized,
            require_owner_change_request,
        )

        snapshot = SqliteRuleRepository._current(connection, request.candidate_id)
        if snapshot is None:
            if (request.rules_version is not None or request.top_per_query is not None
                    or request.round_overrides):
                raise ContractValidationError("No confirmed configuration exists for this round.")
            return request
        validate_snapshot(snapshot)
        if not configuration_initialized(connection, request.candidate_id):
            raise ContractValidationError(
                "Configuration initialization is incomplete; no round started.",
            )
        if request.rules_version is None:
            raise ContractValidationError(
                "Configured round requires the current rules snapshot version.",
            )
        if snapshot.effective_at > now:
            raise ContractValidationError("Configured round cannot use future owner decisions.")
        actual_code = runtime_fingerprint()
        if request.code_revision is not None and request.code_revision != actual_code:
            raise ContractValidationError(
                "Prepared source round uses a different code/runtime revision.",
            )
        request = request.model_copy(update={"code_revision": actual_code})
        if request.round_overrides:
            base_version = snapshot.version
            if request.base_rules_version not in {None, base_version}:
                raise ContractValidationError("Round override base version is stale.")
            for override in request.round_overrides:
                row = connection.execute(
                    "SELECT proposal_json FROM dynamic_rule_proposals WHERE proposal_id = ?",
                    (override.proposal.proposal_id,),
                ).fetchone()
                if row is None or RuleProposal.model_validate_json(row[0]) != override.proposal:
                    raise ContractValidationError(
                        "Round override has no exact saved original question.",
                    )
                require_owner_change_request(
                    connection, override.proposal, allow_consumed_by=request.run_id,
                )
            snapshot = apply_round_overrides(
                snapshot, request.round_overrides, run_id=request.run_id, now=now,
            )
            if request.rules_version not in {base_version, snapshot.version}:
                raise ContractValidationError(
                    "Round override rules version is stale or conflicting.",
                )
            request = request.model_copy(update={
                "rules_version": snapshot.version, "base_rules_version": base_version,
            })
        elif request.base_rules_version is not None:
            raise ContractValidationError("Round override receipt is missing or unsupported.")
        return bind_sourcing_run(snapshot, request, source_ceiling=50)

    @staticmethod
    def _round_counts(connection: sqlite3.Connection, run_id: str) -> tuple[int, int]:
        counts = dict(connection.execute(
            "SELECT kind, count(*) FROM sourcing_attempts WHERE run_id = ? GROUP BY kind",
            (run_id,),
        ).fetchall())
        captures = connection.execute(
            "SELECT count(*) FROM sourcing_read_attempts "
            "WHERE json_extract(request_json, '$.run_id') = ?", (run_id,),
        ).fetchone()[0]
        return counts.get("query", 0), counts.get("detail", 0) + int(captures)

    @staticmethod
    def _budget(
        connection: sqlite3.Connection, source: str, daily_cap: int, now: datetime
    ) -> SourcingBudget:
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
        read_attempts = _read_attempt_ids(connection, source, now)
        first_reads: dict[str, datetime] = {}
        for item in details:
            if item.source_job_id is not None:
                key = " ".join(item.source_job_id.split()).casefold()
                first_reads[key] = min(first_reads.get(key, item.occurred_at), item.occurred_at)
        # Old imports are a conservative observed-job estimate, never reconstructed
        # attempts. New attempts and their stored job must not consume twice.
        legacy_keys = {
            row["source_job_id"]
            for row in connection.execute(
                "SELECT source_job_id FROM sourcing_legacy_reads "
                "WHERE source = ? AND observed_day = ?",
                (source, now.astimezone(SOURCING_DAY).date().isoformat()),
            ).fetchall()
        }
        for row in connection.execute("SELECT job_json FROM normalized_jobs").fetchall():
            job = NormalizedJob.model_validate_json(row["job_json"])
            if (
                job.source == source
                and job.read_attempt_id not in read_attempts
                and job.collected_at.astimezone(SOURCING_DAY).date()
                == now.astimezone(SOURCING_DAY).date()
                and (
                    " ".join(job.source_job_id.split()).casefold() not in first_reads
                    or job.collected_at
                    < first_reads[" ".join(job.source_job_id.split()).casefold()]
                )
            ):
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
        used = len(details) + len(read_attempts) + legacy
        halted = connection.execute(
            "SELECT 1 FROM sourcing_read_halts WHERE source = ? AND platform_day = ?",
            (source, now.astimezone(SOURCING_DAY).date().isoformat()),
        ).fetchone() is not None
        return SourcingBudget(
            source=source,
            daily_cap=daily_cap,
            read_today=used,
            remaining=max(0, daily_cap - used),
            legacy_unmetered=legacy,
            query_attempts_today=sum(item.kind == "query" for item in attempts),
            listing_observations_today=sum(item.listing_count or 0 for item in results),
            halted=halted or any(item.outcome == "gate" for item in results),
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
        read_attempts = _read_attempt_ids(connection, source, now)
        for row in connection.execute("SELECT job_json FROM normalized_jobs").fetchall():
            job = NormalizedJob.model_validate_json(row["job_json"])
            key = " ".join(job.source_job_id.split()).casefold()
            if (
                job.source == source
                and job.read_attempt_id not in read_attempts
                and job.collected_at.astimezone(SOURCING_DAY).date() == day
                and (key not in first_reads or job.collected_at < first_reads[key])
            ):
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
            if connection.execute(
                "SELECT 1 FROM sourcing_read_attempts WHERE attempt_id = ?", (request.attempt_id,),
            ).fetchone():
                raise ContractValidationError("Attempt ID belongs to another sourcing entry point.")
            run = self._get_run(connection, request.run_id)
            self._configured_request(connection, run, now=now)
            self._capture_legacy(connection, run.source, now)
            budget = self._budget(connection, run.source, run.daily_detail_limit, now)
            queries, details = self._round_counts(connection, run.run_id)
            old = connection.execute(
                "SELECT attempt_json FROM sourcing_attempts WHERE attempt_id = ?",
                (request.attempt_id,),
            ).fetchone()
            previous = (
                None
                if old is None
                else SourcingAttempt.model_validate_json(
                    old["attempt_json"],
                )
            )
            if previous is not None and not _same_request(request, previous):
                raise ContractValidationError("An attempt ID cannot change its target.")
            reason: SourcingRefusal | None = (
                "already_reserved"
                if previous is not None
                else refusal_reason(
                    request,
                    run,
                    budget,
                    query_count=queries,
                    detail_count=details,
                    now=now,
                )
            )
            if reason is not None:
                return SourcingPermit(
                    allowed=False,
                    reason=reason,
                    query_remaining=max(0, run.query_limit - queries),
                    detail_remaining=max(0, run.detail_limit - details),
                    budget=budget,
                    attempt=previous,
                )
            attempt = SourcingAttempt(
                **request.model_dump(exclude={"schema_version"}),
                source=run.source,
                occurred_at=now.astimezone(UTC),
            )
            connection.execute(
                "INSERT INTO sourcing_attempts "
                "(attempt_id, run_id, source, kind, occurred_at, attempt_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    attempt.attempt_id,
                    attempt.run_id,
                    attempt.source,
                    attempt.kind,
                    attempt.occurred_at.isoformat(),
                    attempt.model_dump_json(),
                ),
            )
            budget = self._budget(connection, run.source, run.daily_detail_limit, now)
            return SourcingPermit(
                allowed=True,
                reason="allowed",
                attempt=attempt,
                budget=budget,
                query_remaining=max(0, run.query_limit - queries - (request.kind == "query")),
                detail_remaining=max(0, run.detail_limit - details - (request.kind == "detail")),
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
            if (
                attempt.kind == "query"
                and request.outcome == "complete"
                and request.listing_count is None
            ):
                raise ContractValidationError(
                    "Completed queries must record observed listing count."
                )
            run = self._get_run(connection, attempt.run_id)
            if (attempt.kind == "query" and request.outcome == "complete"
                    and run.rules_version is not None):
                captured = connection.execute(
                    "SELECT 1 FROM sourcing_query_selections WHERE attempt_id = ?",
                    (request.attempt_id,),
                ).fetchone()
                if not captured:
                    raise ContractValidationError(
                        "Configured query success requires the actual result capture/selection.",
                    )
            if (
                (run.budget_profile == "muse-expanded-v1" or run.top_per_query is not None)
                and attempt.kind == "query"
                and request.listing_count is not None
                and request.listing_count > (run.top_per_query or 10)
            ):
                raise ContractValidationError(
                    "Expanded queries observe at most the first ten rows."
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
                source=attempt.source,
                completed_at=now.astimezone(UTC),
            )
            connection.execute(
                "INSERT INTO sourcing_results "
                "(attempt_id, source, completed_at, result_json) VALUES (?, ?, ?, ?)",
                (
                    result.attempt_id,
                    result.source,
                    result.completed_at.isoformat(),
                    result.model_dump_json(),
                ),
            )
            if result.outcome == "gate":
                days = {
                    attempt.occurred_at.astimezone(SOURCING_DAY).date().isoformat(),
                    now.astimezone(SOURCING_DAY).date().isoformat(),
                }
                for day in days:
                    connection.execute(
                        "INSERT OR IGNORE INTO sourcing_read_halts VALUES (?, ?, ?)",
                        (attempt.source, day, "gate"),
                    )
            return result
