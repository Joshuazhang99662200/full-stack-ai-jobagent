"""SQLite connection and explicit migration boundary."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources
from pathlib import Path

from jobagent.errors import StorageError

LATEST_SCHEMA_VERSION = 1


class Database:
    """Own SQLite connection setup and schema migrations."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        try:
            connection = sqlite3.connect(self.path)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
        except sqlite3.Error as error:
            raise StorageError(
                "Could not open SQLite database.",
                details={"path": str(self.path), "operation": "connect"},
            ) from error

        try:
            yield connection
        finally:
            connection.close()

    def migrate(self) -> None:
        try:
            with self.connect() as connection:
                current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                if current_version > LATEST_SCHEMA_VERSION:
                    raise StorageError(
                        "SQLite schema is newer than this JobAgent version.",
                        details={
                            "current_version": current_version,
                            "supported_version": LATEST_SCHEMA_VERSION,
                        },
                    )
                if current_version == 0:
                    migration = (
                        resources.files("jobagent.storage.migrations")
                        .joinpath("0001_candidate.sql")
                        .read_text(encoding="utf-8")
                    )
                    connection.executescript(migration)
        except StorageError:
            raise
        except (OSError, sqlite3.Error) as error:
            raise StorageError(
                "Could not migrate SQLite database.",
                details={"path": str(self.path), "operation": "migrate"},
            ) from error

