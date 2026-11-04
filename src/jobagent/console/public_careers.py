"""Read an existing discovery snapshot without migrating or creating a database."""

import sqlite3
from pathlib import Path

from jobagent.schemas.console import ConsolePublicCareers
from jobagent.schemas.public_careers import PublicCareerRecord, PublicCareerRun
from jobagent.storage.database import LATEST_SCHEMA_VERSION


def read_public_careers(database: Path, candidate_id: str) -> ConsolePublicCareers:
    if not database.is_file():
        return ConsolePublicCareers()
    connection = None
    try:
        connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version > LATEST_SCHEMA_VERSION:
            raise ValueError("Unsupported source version")
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('public_career_records', 'public_career_runs')"
            )
        }
        if not tables:
            return ConsolePublicCareers()
        if len(tables) != 2 or version < 34:
            raise ValueError("Incomplete discovery source")
        records = [
            PublicCareerRecord.model_validate_json(row[0])
            for row in connection.execute(
                "SELECT record_json FROM public_career_records "
                "WHERE candidate_id=? ORDER BY rowid", (candidate_id,),
            )
        ]
        runs = [
            PublicCareerRun.model_validate_json(row[0])
            for row in connection.execute(
                "SELECT run_json FROM public_career_runs "
                "WHERE candidate_id=? ORDER BY rowid", (candidate_id,),
            )
        ]
        if any(item.candidate_id != candidate_id for item in records) or any(
            item.candidate_id != candidate_id for item in runs
        ):
            raise ValueError("Discovery candidate mismatch")
        return ConsolePublicCareers(status="complete", records=records, runs=runs)
    except (OSError, ValueError, sqlite3.Error):
        return ConsolePublicCareers(status="invalid")
    finally:
        if connection:
            connection.close()
