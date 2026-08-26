"""SQLite adapter for the append-only application audit trail."""

import sqlite3
from datetime import UTC, datetime

from jobagent.errors import StorageError
from jobagent.schemas.applications import ApplicationAudit
from jobagent.storage.database import Database


def _now() -> str:
    return datetime.now(UTC).isoformat()


class SqliteApplicationAuditRepository:
    """Persist one immutable row per delivery attempt.

    Rows are never updated or deleted: an audit that could be rewritten is not an
    audit. Only IDs, digests and outcomes are stored, never resume or message text.
    """

    def __init__(self, database: Database) -> None:
        self.database = database

    def append_audit(self, audit: ApplicationAudit) -> None:
        try:
            with self.database.connect() as connection, connection:
                connection.execute(
                    """
                    INSERT INTO application_audits (
                        audit_id, application_id, attempt, result, audit_json, recorded_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        audit.audit_id,
                        audit.application_id,
                        audit.attempt,
                        audit.result.value,
                        audit.model_dump_json(),
                        _now(),
                    ),
                )
        except sqlite3.Error as error:
            self._raise_storage_error("append application audit", error)

    def next_attempt(self, application_id: str) -> int:
        try:
            with self.database.connect() as connection:
                row = connection.execute(
                    "SELECT MAX(attempt) AS highest FROM application_audits "
                    "WHERE application_id = ?",
                    (application_id,),
                ).fetchone()
        except sqlite3.Error as error:
            self._raise_storage_error("read application audit attempts", error)
        highest = None if row is None else row["highest"]
        return 1 if highest is None else int(highest) + 1

    def list_audits(self, application_id: str | None = None) -> list[ApplicationAudit]:
        query = "SELECT audit_json FROM application_audits"
        parameters: tuple[str, ...] = ()
        if application_id is not None:
            query += " WHERE application_id = ?"
            parameters = (application_id,)
        query += " ORDER BY application_id, attempt"
        try:
            with self.database.connect() as connection:
                rows = connection.execute(query, parameters).fetchall()
        except sqlite3.Error as error:
            self._raise_storage_error("list application audits", error)
        return [ApplicationAudit.model_validate_json(row["audit_json"]) for row in rows]

    def _raise_storage_error(self, operation: str, error: sqlite3.Error) -> None:
        raise StorageError(
            f"Could not {operation}.",
            details={"path": str(self.database.path), "operation": operation},
        ) from error
