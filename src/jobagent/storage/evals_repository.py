"""SQLite adapter for evaluation signals: harness versions and online profiles."""

import sqlite3
from typing import Never

from jobagent.errors import StorageError
from jobagent.schemas.evals import HarnessVersion
from jobagent.schemas.profile import ProfileSnapshot, ProfileVersion
from jobagent.storage.database import Database


class SqliteEvalsRepository:
    """Every row here is only ever added."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def save_harness_version(self, version: HarnessVersion) -> None:
        """Keep a version once; the same files seen again keep their first record."""
        try:
            with self.database.connect() as connection, connection:
                connection.execute(
                    "INSERT OR IGNORE INTO harness_versions "
                    "(version_id, digest, version_json, recorded_at) VALUES (?, ?, ?, ?)",
                    (
                        version.version_id,
                        version.digest,
                        version.model_dump_json(),
                        version.recorded_at.isoformat(),
                    ),
                )
        except sqlite3.Error as error:
            self._raise("save harness version", error)

    def get_harness_version(self, version_id: str) -> HarnessVersion | None:
        try:
            with self.database.connect() as connection:
                row = connection.execute(
                    "SELECT version_json AS body FROM harness_versions WHERE version_id = ?",
                    (version_id,),
                ).fetchone()
        except sqlite3.Error as error:
            self._raise("read harness version", error)
        return HarnessVersion.model_validate_json(row["body"]) if row else None

    def save_profile_snapshot(self, snapshot: ProfileSnapshot) -> None:
        self._write(
            "save profile snapshot",
            "INSERT INTO profile_snapshots "
            "(snapshot_id, platform, captured_at, digest, snapshot_json) VALUES (?, ?, ?, ?, ?)",
            (
                snapshot.snapshot_id,
                snapshot.platform,
                snapshot.captured_at.isoformat(),
                snapshot.digest,
                snapshot.model_dump_json(),
            ),
        )

    def get_profile_snapshot(self, snapshot_id: str) -> ProfileSnapshot | None:
        rows = self._read(
            "read profile snapshot",
            "SELECT snapshot_json AS body FROM profile_snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        )
        return ProfileSnapshot.model_validate_json(rows[0]["body"]) if rows else None

    def save_profile_version(self, version: ProfileVersion) -> None:
        self._write(
            "save profile version",
            "INSERT INTO profile_versions "
            "(version_id, platform, digest, effective_at, version_json) VALUES (?, ?, ?, ?, ?)",
            (
                version.version_id,
                version.platform,
                version.digest,
                version.effective_at.isoformat(),
                version.model_dump_json(),
            ),
        )

    def profile_versions(self, platform: str) -> list[ProfileVersion]:
        """A board's profile versions, oldest first."""
        rows = self._read(
            "list profile versions",
            "SELECT version_json AS body FROM profile_versions WHERE platform = ? "
            "ORDER BY effective_at, version_id",
            (platform,),
        )
        return [ProfileVersion.model_validate_json(row["body"]) for row in rows]

    def _write(self, operation: str, sql: str, parameters: tuple[object, ...]) -> None:
        try:
            with self.database.connect() as connection, connection:
                connection.execute(sql, parameters)
        except sqlite3.Error as error:
            self._raise(operation, error)

    def _read(self, operation: str, sql: str, parameters: tuple[object, ...]) -> list[sqlite3.Row]:
        try:
            with self.database.connect() as connection:
                return list(connection.execute(sql, parameters).fetchall())
        except sqlite3.Error as error:
            self._raise(operation, error)

    def _raise(self, operation: str, error: sqlite3.Error) -> Never:
        raise StorageError(
            f"Could not {operation}.",
            details={"path": str(self.database.path), "operation": operation},
        ) from error
