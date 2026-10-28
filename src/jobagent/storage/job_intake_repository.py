"""Transactional human intake state plus immutable transition and signal history."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from pydantic_core import to_jsonable_python

from jobagent.errors import ContractValidationError, StorageError
from jobagent.jobs.jd_snapshot import canonical_digest
from jobagent.jobs.job_intake import target_key
from jobagent.schemas.job_intake import IntakeHistory, IntakeRecord, IntakeRequest
from jobagent.schemas.search_learning import SearchSignal
from jobagent.storage.database import Database


class SqliteJobIntakeRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        try:
            with self.database.connect() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
        except sqlite3.Error as error:
            raise StorageError("Job intake ledger unavailable.") from error

    @staticmethod
    def current(connection: sqlite3.Connection, intake_id: str, candidate_id: str) -> IntakeRecord:
        row = connection.execute(
            "SELECT state_json FROM job_intakes WHERE intake_id = ? AND candidate_id = ?",
            (intake_id, candidate_id),
        ).fetchone()
        if row is None:
            raise ContractValidationError("Intake not found for this candidate.")
        return IntakeRecord.model_validate_json(row["state_json"])

    def get(self, intake_id: str, candidate_id: str) -> IntakeRecord:
        with self.database.connect() as connection:
            return self.current(connection, intake_id, candidate_id)

    @staticmethod
    def append(
        connection: sqlite3.Connection,
        state: IntakeRecord,
        event_id: str,
        kind: str,
        digest: str,
        command_digest: str | None = None,
    ) -> None:
        history = IntakeHistory(
            event_id=event_id,
            kind=kind,
            input_digest=digest,
            state=state,
            command_digest=command_digest,
        )
        connection.execute(
            "INSERT INTO intake_events VALUES (?, ?, ?, ?, ?)",
            (
                event_id,
                state.intake_id,
                state.version,
                digest,
                history.model_dump_json(),
            ),
        )
        connection.execute(
            "UPDATE job_intakes SET state_json = ? WHERE intake_id = ?",
            (state.model_dump_json(), state.intake_id),
        )

    def enqueue(self, request: IntakeRequest, *, now: datetime) -> IntakeRecord:
        if now.tzinfo is None or request.occurred_at > now:
            raise ContractValidationError("Intake cannot come from the future.")
        digest = canonical_digest(request.model_dump(mode="json"))
        key = target_key(request)
        with self.write() as connection:
            old = connection.execute(
                "SELECT * FROM intake_requests WHERE request_id = ?",
                (request.request_id,),
            ).fetchone()
            if old is not None:
                if old["input_digest"] != digest:
                    raise ContractValidationError("Request ID has different content.")
                return self.current(connection, old["intake_id"], request.candidate_id)
            found = connection.execute(
                "SELECT state_json FROM job_intakes WHERE target_key = ?",
                (key,),
            ).fetchone()
            if found is None:
                state = IntakeRecord(
                    intake_id="INTAKE_" + key[7:31],
                    candidate_id=request.candidate_id,
                    domain=request.domain,
                    platform=request.platform,
                    requests=[request],
                    version=1,
                    created_at=now,
                    updated_at=now,
                    job_url=request.job_url,
                    source_job_id=request.source_job_id,
                )
                connection.execute(
                    "INSERT INTO job_intakes VALUES (?, ?, ?, ?, ?)",
                    (
                        state.intake_id,
                        state.candidate_id,
                        state.domain,
                        key,
                        state.model_dump_json(),
                    ),
                )
            else:
                previous = IntakeRecord.model_validate_json(found["state_json"])
                if previous.closed or previous.merged_into:
                    raise ContractValidationError(
                        "This target is closed; explicitly reopen with a new target."
                    )
                state = previous.model_copy(
                    update={
                        "requests": sorted(
                            [*previous.requests, request],
                            key=lambda r: (r.occurred_at, r.request_id),
                        ),
                        "version": previous.version + 1,
                        "updated_at": now,
                        "plan_id": None if request.job_preference is not None else previous.plan_id,
                        "signal_id": None
                        if request.job_preference is not None
                        else previous.signal_id,
                    }
                )
            event_id = "ENQUEUE_" + canonical_digest(request.request_id)[7:]
            self.append(connection, state, event_id, "enqueue", digest)
            connection.execute(
                "INSERT INTO intake_requests VALUES (?, ?, ?)",
                (request.request_id, digest, state.intake_id),
            )
            return state

    def update(
        self,
        intake_id: str,
        candidate_id: str,
        *,
        event_id: str,
        expected_version: int,
        kind: str,
        changes: dict[str, object],
        now: datetime,
        signal: SearchSignal | None = None,
        command_digest: str | None = None,
    ) -> IntakeRecord:
        digest = canonical_digest(
            [
                intake_id,
                candidate_id,
                expected_version,
                kind,
                to_jsonable_python(changes),
                signal.model_dump(mode="json") if signal else None,
            ]
        )
        with self.write() as connection:
            current = self.current(connection, intake_id, candidate_id)
            old = connection.execute(
                "SELECT * FROM intake_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if old is not None:
                if old["intake_id"] != intake_id or old["input_digest"] != digest:
                    raise ContractValidationError("Event ID has different content.")
                return IntakeHistory.model_validate_json(old["event_json"]).state
            if current.version != expected_version:
                raise ContractValidationError("Intake changed; reload its current version.")
            if current.closed or current.merged_into:
                raise ContractValidationError("Closed or merged intake cannot be revived.")
            if now.tzinfo is None or now < current.updated_at:
                raise ContractValidationError("Intake updates must be chronological.")
            state = IntakeRecord.model_validate(
                {
                    **current.model_dump(),
                    **changes,
                    "version": current.version + 1,
                    "updated_at": now,
                }
            )
            if signal is not None:
                if signal.candidate_id != candidate_id:
                    raise ContractValidationError("Signal belongs to another candidate.")
                connection.execute(
                    "INSERT OR IGNORE INTO intake_signals VALUES (?, ?, ?, ?, ?)",
                    (
                        signal.event_id,
                        candidate_id,
                        state.domain,
                        intake_id,
                        signal.model_dump_json(),
                    ),
                )
            self.append(connection, state, event_id, kind, digest, command_digest)
            return state

    @staticmethod
    def scoped(
        connection: sqlite3.Connection, candidate_id: str, domain: str
    ) -> list[IntakeRecord]:
        return [
            IntakeRecord.model_validate_json(row["state_json"])
            for row in connection.execute(
                "SELECT state_json FROM job_intakes WHERE candidate_id = ? AND domain = ? "
                "ORDER BY intake_id",
                (candidate_id, domain),
            ).fetchall()
        ]

    def list_records(self, candidate_id: str, domain: str) -> list[IntakeRecord]:
        with self.database.connect() as connection:
            return self.scoped(connection, candidate_id, domain)

    def history(self, intake_id: str, candidate_id: str) -> list[IntakeHistory]:
        with self.database.connect() as connection:
            self.current(connection, intake_id, candidate_id)
            rows = connection.execute(
                "SELECT event_json FROM intake_events WHERE intake_id = ? ORDER BY version",
                (intake_id,),
            ).fetchall()
        return [IntakeHistory.model_validate_json(row["event_json"]) for row in rows]

    def signals(self, candidate_id: str, domain: str) -> list[SearchSignal]:
        with self.database.connect() as connection:
            return [
                SearchSignal.model_validate_json(row["signal_json"])
                for row in connection.execute(
                    "SELECT signal_json FROM intake_signals WHERE candidate_id = ? AND domain = ? "
                    "ORDER BY rowid",
                    (candidate_id, domain),
                ).fetchall()
            ]

    @staticmethod
    def source_digest(records: list[IntakeRecord]) -> str:
        return canonical_digest(
            [
                [
                    s.intake_id,
                    s.job_id,
                    s.snapshot_id,
                    s.feature_set_id,
                    s.signal_id,
                    s.closed,
                    s.merged_into,
                ]
                for s in records
            ]
        )
