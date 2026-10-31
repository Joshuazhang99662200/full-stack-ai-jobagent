"""SQLite connection and explicit migration boundary."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources
from pathlib import Path

from jobagent.errors import StorageError

LATEST_SCHEMA_VERSION = 33
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
    14: "0014_sourcing_budget.sql",
    15: "0015_jd_knowledge.sql",
    16: "0016_query_plans.sql",
    17: "0017_sent_tracking.sql",
    18: "0018_job_intake.sql",
    19: "0019_host_adoption.sql",
    20: "0020_host_backfill.sql",
    21: "0021_message_diff.sql",
    22: "0022_pipeline.sql",
    23: "0023_pipeline_adoption.sql",
    24: "0024_pipeline_metrics.sql",
    25: "0025_pipeline_rules.sql",
    26: "0026_pipeline_backfill.sql",
    27: "0027_worker.sql",
    28: "0028_paged_feedback.sql",
    29: "0029_reliability.sql",
    30: "0030_dynamic_rules.sql",
    31: "0031_configuration.sql",
    32: "0032_query_receipts.sql",
    33: "0033_mcp_calls.sql",
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
                if 14 <= current_version <= 17:
                    tables = {
                        row[0] for row in connection.execute(
                            "SELECT name FROM sqlite_master WHERE type = 'table'",
                        )
                    }
                    if "worker_fetch_receipts" in tables and "sourcing_runs" not in tables:
                        raise StorageError(
                            "Conflicting unpublished local schema; reconcile an isolated copy "
                            "before upgrading. The database has not been changed.",
                        )
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
