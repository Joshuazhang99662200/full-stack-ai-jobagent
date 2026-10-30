"""Atomic attempt-based read budgets; reservations are never refunded."""

import hashlib
import json
from datetime import datetime, timedelta, timezone

from jobagent.errors import ContractValidationError
from jobagent.schemas.sourcing import ReadOutcome, ReadReceipt, ReadReservation
from jobagent.storage.database import Database
from jobagent.storage.sourcing_repository import SqliteSourcingRepository

PLATFORM_TIME = timezone(timedelta(hours=8))


def platform_day(now: datetime) -> str:
    if now.tzinfo is None:
        raise ContractValidationError("Read budget clock must include a timezone.")
    return now.astimezone(PLATFORM_TIME).date().isoformat()


class SqliteReadRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def reserve(
        self, request: ReadReservation, *, daily_cap: int, now: datetime,
        legacy_reads: int = 0,
    ) -> ReadReceipt:
        day = platform_day(now)
        if legacy_reads < 0:
            raise ContractValidationError("Invalid negative legacy read estimate.")
        if (request.profile != "standard" or request.expected_daily_cap != daily_cap
                or not 1 <= daily_cap <= 50):
            raise ContractValidationError("Requested profile/cap differs from effective budget.")
        body = json.dumps(request.model_dump(mode="json"), sort_keys=True)
        digest = "sha256:" + hashlib.sha256(body.encode()).hexdigest()
        with self.database.connect() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute(
                "SELECT 1 FROM sourcing_attempts WHERE attempt_id = ?", (request.attempt_id,),
            ).fetchone():
                raise ContractValidationError("Read ID belongs to another sourcing entry point.")
            previous = connection.execute(
                "SELECT * FROM sourcing_read_attempts WHERE attempt_id = ?", (request.attempt_id,),
            ).fetchone()
            if previous:
                if previous["request_digest"] != digest or previous["platform_day"] != day:
                    raise ContractValidationError("Read attempt already holds different input/day.")
                reserved_at = datetime.fromisoformat(previous["reserved_at"])
                allowed = False
            else:
                SqliteSourcingRepository._capture_legacy(connection, request.source, now)
                budget = SqliteSourcingRepository._budget(
                    connection, request.source, daily_cap, now,
                )
                if budget.halted:
                    raise ContractValidationError("Source is stopped; user intervention required.")
                used = budget.read_today + max(0, legacy_reads - budget.legacy_unmetered)
                if used >= daily_cap:
                    raise ContractValidationError("Source detail-read budget is exhausted.")
                reserved_at = now
                allowed = True
                connection.execute(
                    "INSERT INTO sourcing_read_attempts VALUES (?, ?, ?, ?, ?, ?, NULL)",
                    (request.attempt_id, request.source, day, digest, body, now.isoformat()),
                )
        return ReadReceipt(
            attempt_id=request.attempt_id, source=request.source, request_digest=digest,
            reserved_at=reserved_at, daily_cap=daily_cap, profile=request.profile,
            allowed=allowed,
        )

    def record(self, outcome: ReadOutcome, *, now: datetime) -> None:
        observed_day = platform_day(now)
        body = outcome.model_dump_json()
        with self.database.connect() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM sourcing_read_attempts WHERE attempt_id = ?", (outcome.attempt_id,),
            ).fetchone()
            if row is None:
                raise ContractValidationError("Read attempt was not reserved.")
            if row["result_json"] is not None:
                if row["result_json"] != body:
                    raise ContractValidationError("Read attempt already has a different result.")
                return
            connection.execute(
                "UPDATE sourcing_read_attempts SET result_json = ? WHERE attempt_id = ?",
                (body, outcome.attempt_id),
            )
            if outcome.status not in {"read", "failed"}:
                for halted_day in {row["platform_day"], observed_day}:
                    connection.execute(
                        "INSERT OR IGNORE INTO sourcing_read_halts VALUES (?, ?, ?)",
                        (row["source"], halted_day, outcome.status),
                    )

    def used(self, source: str, *, now: datetime) -> int:
        with self.database.connect() as connection:
            return int(connection.execute(
                "SELECT count(*) FROM sourcing_read_attempts WHERE source = ? AND platform_day = ?",
                (source, platform_day(now)),
            ).fetchone()[0])
