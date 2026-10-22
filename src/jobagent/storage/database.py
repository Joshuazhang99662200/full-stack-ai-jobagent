"""SQLite connection and explicit migration boundary."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources
from pathlib import Path

from jobagent.errors import StorageError

LATEST_SCHEMA_VERSION = 13
_MIGRATION_FILES = {
    1: "0001_candidate.sql",
    2: "0002_jobs.sql",
    3: "0003_applications.sql",
    4: "0004_outreach.sql",
    5: "0005_conversations.sql",
    6: "0006_patrol.sql",
    7: "0007_patrol_finish.sql",
    8: "0008_patrol_snapshots.sql",
    9: "0009_outreach_withdrawals.sql",
    10: "0010_evals_signals.sql",
    11: "0011_outreach_withdrawn_result.sql",
    12: "0012_job_searches.sql",
    13: "0013_profile_flywheel.sql",
}


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
                for target_version in range(current_version + 1, LATEST_SCHEMA_VERSION + 1):
                    migration = (
                        resources.files("jobagent.storage.migrations")
                        .joinpath(_MIGRATION_FILES[target_version])
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
