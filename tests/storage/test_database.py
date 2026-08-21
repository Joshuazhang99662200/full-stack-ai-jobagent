import sqlite3
from pathlib import Path

import pytest

from jobagent.errors import StorageError
from jobagent.storage.database import Database


def test_migration_creates_candidate_schema_and_enables_foreign_keys(tmp_path: Path) -> None:
    database = Database(tmp_path / "candidate.sqlite3")

    database.migrate()

    with database.connect() as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert version == 2
    assert foreign_keys == 1
    assert {
        "candidate_profiles",
        "evidence_items",
        "resume_ingestions",
        "interview_events",
    } <= tables


def test_migration_is_idempotent(tmp_path: Path) -> None:
    database = Database(tmp_path / "candidate.sqlite3")
    database.migrate()
    database.migrate()

    with database.connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2


def test_connection_enforces_candidate_foreign_keys(tmp_path: Path) -> None:
    database = Database(tmp_path / "candidate.sqlite3")
    database.migrate()

    with database.connect() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO evidence_items (
                evidence_id, candidate_id, evidence_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("EVID_001", "CAND_MISSING", "{}", "now", "now"),
        )


def test_invalid_database_location_raises_storage_error(tmp_path: Path) -> None:
    database = Database(tmp_path / "missing" / "candidate.sqlite3")

    with pytest.raises(StorageError, match="open SQLite database"):
        database.migrate()
