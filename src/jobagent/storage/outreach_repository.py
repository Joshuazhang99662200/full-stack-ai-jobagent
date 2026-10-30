"""SQLite adapter for outreach batches, approvals, the send ledger and leases."""

import sqlite3
from datetime import datetime, timedelta
from typing import Never

from jobagent.errors import StorageError
from jobagent.schemas.outreach import (
    OutreachApproval,
    OutreachAsk,
    OutreachAudit,
    OutreachBatch,
)
from jobagent.storage.database import Database


class SqliteOutreachRepository:
    """Persist outreach state. The audit ledger has no update or delete path."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def save_batch(self, batch: OutreachBatch) -> None:
        self._write(
            "save outreach batch",
            "INSERT INTO outreach_batches (batch_id, batch_json, created_at) VALUES (?, ?, ?)",
            (batch.batch_id, batch.model_dump_json(), batch.created_at.isoformat()),
        )

    def get_batch(self, batch_id: str) -> OutreachBatch | None:
        row = self._read_one(
            "read outreach batch",
            "SELECT batch_json AS body FROM outreach_batches WHERE batch_id = ?",
            (batch_id,),
        )
        return None if row is None else OutreachBatch.model_validate_json(row)

    def save_ask(self, ask: OutreachAsk) -> None:
        self._write(
            "save outreach question",
            "INSERT OR REPLACE INTO outreach_asks (ask_id, batch_id, ask_json) VALUES (?, ?, ?)",
            (ask.ask_id, ask.batch_id, ask.model_dump_json()),
        )

    def get_ask(self, ask_id: str) -> OutreachAsk | None:
        row = self._read_one(
            "read outreach question",
            "SELECT ask_json AS body FROM outreach_asks WHERE ask_id = ?",
            (ask_id,),
        )
        return None if row is None else OutreachAsk.model_validate_json(row)

    def save_approval(self, approval: OutreachApproval) -> None:
        # One approval per batch: a second answer needs a new batch and a new question.
        self._write(
            "save outreach approval",
            "INSERT INTO outreach_approvals (approval_id, batch_id, approval_json) "
            "VALUES (?, ?, ?)",
            (approval.approval_id, approval.batch_id, approval.model_dump_json()),
        )

    def withdraw(self, batch_id: str, reason: str, withdrawn_at: datetime) -> None:
        self._write(
            "withdraw outreach batch",
            "INSERT INTO outreach_withdrawals (batch_id, reason, withdrawn_at) VALUES (?, ?, ?)",
            (batch_id, reason, withdrawn_at.isoformat()),
        )

    def is_withdrawn(self, batch_id: str) -> bool:
        try:
            with self.database.connect() as connection:
                row = connection.execute(
                    "SELECT 1 FROM outreach_withdrawals WHERE batch_id = ?", (batch_id,)
                ).fetchone()
        except sqlite3.Error as error:
            self._raise("read outreach withdrawal", error)
        return row is not None

    def get_approval(self, batch_id: str) -> OutreachApproval | None:
        row = self._read_one(
            "read outreach approval",
            "SELECT approval_json AS body FROM outreach_approvals WHERE batch_id = ?",
            (batch_id,),
        )
        return None if row is None else OutreachApproval.model_validate_json(row)

    def append_audit(
        self, audit: OutreachAudit, *, connection: sqlite3.Connection | None = None
    ) -> None:
        sql = """
            INSERT INTO outreach_audits (
                audit_id, batch_id, number, job_id, platform, result, audit_json, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """
        parameters = (
                audit.audit_id,
                audit.batch_id,
                audit.number,
                audit.job_id,
                audit.platform,
                audit.result.value,
                audit.model_dump_json(),
                audit.recorded_at.isoformat(),
        )
        if connection is not None:
            connection.execute(sql, parameters)
        else:
            self._write("append outreach audit", sql, parameters)

    def list_audits(self) -> list[OutreachAudit]:
        try:
            with self.database.connect() as connection:
                rows = connection.execute(
                    "SELECT audit_json FROM outreach_audits ORDER BY recorded_at, audit_id"
                ).fetchall()
        except sqlite3.Error as error:
            self._raise("list outreach audits", error)
        return [OutreachAudit.model_validate_json(row["audit_json"]) for row in rows]

    def acquire_lease(
        self, platform: str, session_id: str, *, now: datetime, ttl_seconds: int
    ) -> bool:
        """Take or renew the platform lease. Refuse while another session holds it."""
        expires = (now + timedelta(seconds=ttl_seconds)).isoformat()
        try:
            with self.database.connect() as connection, connection:
                row = connection.execute(
                    "SELECT session_id, expires_at FROM outreach_leases WHERE platform = ?",
                    (platform,),
                ).fetchone()
                held_by_other = (
                    row is not None
                    and row["session_id"] != session_id
                    and datetime.fromisoformat(row["expires_at"]) > now
                )
                if held_by_other:
                    return False
                connection.execute(
                    "INSERT OR REPLACE INTO outreach_leases (platform, session_id, expires_at) "
                    "VALUES (?, ?, ?)",
                    (platform, session_id, expires),
                )
        except sqlite3.Error as error:
            self._raise("acquire outreach lease", error)
        return True

    def holds_lease(self, platform: str, session_id: str, *, now: datetime) -> bool:
        try:
            with self.database.connect() as connection:
                row = connection.execute(
                    "SELECT session_id, expires_at FROM outreach_leases WHERE platform = ?",
                    (platform,),
                ).fetchone()
        except sqlite3.Error as error:
            self._raise("read outreach lease", error)
        return (
            row is not None
            and row["session_id"] == session_id
            and datetime.fromisoformat(row["expires_at"]) > now
        )

    def release_lease(self, platform: str, session_id: str) -> bool:
        try:
            with self.database.connect() as connection, connection:
                cursor = connection.execute(
                    "DELETE FROM outreach_leases WHERE platform = ? AND session_id = ?",
                    (platform, session_id),
                )
        except sqlite3.Error as error:
            self._raise("release outreach lease", error)
        return cursor.rowcount > 0

    def _write(self, operation: str, sql: str, parameters: tuple[object, ...]) -> None:
        try:
            with self.database.connect() as connection, connection:
                connection.execute(sql, parameters)
        except sqlite3.Error as error:
            self._raise(operation, error)

    def _read_one(self, operation: str, sql: str, parameters: tuple[object, ...]) -> str | None:
        try:
            with self.database.connect() as connection:
                row = connection.execute(sql, parameters).fetchone()
        except sqlite3.Error as error:
            self._raise(operation, error)
        return None if row is None else str(row["body"])

    def _raise(self, operation: str, error: sqlite3.Error) -> Never:
        raise StorageError(
            f"Could not {operation}.",
            details={"path": str(self.database.path), "operation": operation},
        ) from error
