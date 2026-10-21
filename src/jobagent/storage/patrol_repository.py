"""SQLite adapter for recorded patrol checks. Append-only."""

import sqlite3
from datetime import datetime
from typing import Never

from jobagent.errors import ContractValidationError, StorageError
from jobagent.schemas.patrol import PatrolCheck, PatrolSnapshot
from jobagent.storage.database import Database


class SqlitePatrolRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def record(self, check: PatrolCheck) -> None:
        try:
            with self.database.connect() as connection, connection:
                connection.execute(
                    "INSERT INTO patrol_checks (check_id, checked_at, check_json) VALUES (?, ?, ?)",
                    (check.check_id, check.checked_at.isoformat(), check.model_dump_json()),
                )
        except sqlite3.Error as error:
            self._raise("record patrol check", error)

    def finish(self, check_id: str, finished_at: datetime) -> PatrolCheck:
        try:
            with self.database.connect() as connection, connection:
                row = connection.execute(
                    "SELECT check_json AS body FROM patrol_checks WHERE check_id = ?",
                    (check_id,),
                ).fetchone()
                if row is None:
                    raise ContractValidationError(
                        "Patrol check was not found.", details={"check_id": check_id}
                    )
                connection.execute(
                    "INSERT INTO patrol_finishes (check_id, finished_at) VALUES (?, ?)",
                    (check_id, finished_at.isoformat()),
                )
        except sqlite3.IntegrityError as error:
            raise ContractValidationError(
                "This patrol check is already finished.", details={"check_id": check_id}
            ) from error
        except sqlite3.Error as error:
            self._raise("finish patrol check", error)
        check = PatrolCheck.model_validate_json(row["body"])
        return check.model_copy(update={"finished_at": finished_at})

    def latest_finished(self) -> PatrolCheck | None:
        return self._one(
            "SELECT c.check_json AS body, f.finished_at AS finished FROM patrol_checks c "
            "JOIN patrol_finishes f ON f.check_id = c.check_id "
            "ORDER BY c.checked_at DESC LIMIT 1"
        )

    def latest_open(self) -> PatrolCheck | None:
        """The newest check that started and never finished, if it is the newest of all."""
        latest = self._one(
            "SELECT c.check_json AS body, f.finished_at AS finished FROM patrol_checks c "
            "LEFT JOIN patrol_finishes f ON f.check_id = c.check_id "
            "ORDER BY c.checked_at DESC LIMIT 1"
        )
        return latest if latest is not None and latest.finished_at is None else None

    def save_snapshot(self, snapshot: PatrolSnapshot) -> None:
        try:
            with self.database.connect() as connection, connection:
                connection.execute(
                    "INSERT INTO patrol_snapshots "
                    "(snapshot_id, platform, captured_at, snapshot_json) VALUES (?, ?, ?, ?)",
                    (
                        snapshot.snapshot_id,
                        snapshot.platform,
                        snapshot.captured_at.isoformat(),
                        snapshot.model_dump_json(),
                    ),
                )
        except sqlite3.Error as error:
            self._raise("save patrol snapshot", error)

    def snapshots(self, platform: str, limit: int = 20) -> list[PatrolSnapshot]:
        """Newest first."""
        try:
            with self.database.connect() as connection:
                rows = connection.execute(
                    "SELECT snapshot_json AS body FROM patrol_snapshots WHERE platform = ? "
                    "ORDER BY captured_at DESC LIMIT ?",
                    (platform, limit),
                ).fetchall()
        except sqlite3.Error as error:
            self._raise("read patrol snapshots", error)
        return [PatrolSnapshot.model_validate_json(row["body"]) for row in rows]

    def all_snapshots(self) -> list[PatrolSnapshot]:
        """Every kept snapshot of every board, oldest first."""
        try:
            with self.database.connect() as connection:
                rows = connection.execute(
                    "SELECT snapshot_json AS body FROM patrol_snapshots ORDER BY captured_at"
                ).fetchall()
        except sqlite3.Error as error:
            self._raise("read patrol snapshots", error)
        return [PatrolSnapshot.model_validate_json(row["body"]) for row in rows]

    def _one(self, sql: str) -> PatrolCheck | None:
        try:
            with self.database.connect() as connection:
                row = connection.execute(sql).fetchone()
        except sqlite3.Error as error:
            self._raise("read patrol checks", error)
        if row is None:
            return None
        check = PatrolCheck.model_validate_json(row["body"])
        finished = row["finished"]
        return check.model_copy(
            update={"finished_at": datetime.fromisoformat(finished) if finished else None}
        )

    def _raise(self, operation: str, error: sqlite3.Error) -> Never:
        raise StorageError(
            f"Could not {operation}.",
            details={"path": str(self.database.path), "operation": operation},
        ) from error
