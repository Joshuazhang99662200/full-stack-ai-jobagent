"""Discovery projection is read-only and never invents a contact lifecycle."""

import sqlite3
from datetime import UTC, datetime

from jobagent.connectors.public_careers import identity
from jobagent.console.projection import snapshot
from jobagent.schemas.job_intelligence import JobListing
from jobagent.schemas.public_careers import PublicCareerRecord, PublicCareerRun
from jobagent.storage.database import LATEST_SCHEMA_VERSION

NOW = datetime(2026, 11, 3, 1, tzinfo=UTC)


def record(candidate="CAND_DEMO"):
    return PublicCareerRecord(
        candidate_id=candidate,
        provider="greenhouse",
        board="synthetic-board",
        source_job_id="101",
        job_id=identity("public_careers:greenhouse:synthetic-board", "101"),
        run_id="SYNTHETIC_RUN",
        listing=JobListing(
            source="public_careers:greenhouse:synthetic-board",
            source_job_id="101",
            title="Synthetic role",
            company="Synthetic company",
            location="Shanghai",
            url="https://boards.greenhouse.io/synthetic-board/jobs/101",
            collected_at=NOW,
        ),
        region_decision="review",
    )


def source_tables(database):
    connection = sqlite3.connect(database)
    connection.execute(f"PRAGMA user_version={LATEST_SCHEMA_VERSION}")
    connection.execute(
        "CREATE TABLE public_career_records(candidate_id TEXT, record_json TEXT)"
    )
    connection.execute("CREATE TABLE public_career_runs(candidate_id TEXT, run_json TEXT)")
    return connection


def test_missing_discovery_source_is_explicit_and_does_not_create_database(tmp_path):
    database = tmp_path / "absent.sqlite3"
    result = snapshot(database, tmp_path, "CAND_DEMO")

    assert result.public_careers.status == "missing"
    assert result.public_careers.records == []
    assert result.public_careers.runs == []
    assert not database.exists()


def test_old_database_is_not_migrated_or_reported_as_verified_empty(tmp_path):
    database = tmp_path / "old.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA user_version=33")
        connection.execute("CREATE TABLE existing(value TEXT)")
    before = database.read_bytes()

    result = snapshot(database, tmp_path, "CAND_DEMO")

    assert result.public_careers.status == "missing"
    assert database.read_bytes() == before


def test_discoveries_and_runs_are_candidate_scoped_without_contact_states(tmp_path):
    database = tmp_path / "public.sqlite3"
    own, other = record(), record("CAND_OTHER")
    run = PublicCareerRun(
        run_id="SYNTHETIC_RUN", candidate_id="CAND_DEMO", rules_version="sha256:synthetic",
        started_at=NOW, status="partial", raw_returned=4, taken=1,
    )
    with source_tables(database) as connection:
        for item in [own, other]:
            connection.execute(
                "INSERT INTO public_career_records VALUES (?, ?)",
                (item.candidate_id, item.model_dump_json()),
            )
        connection.execute(
            "INSERT INTO public_career_runs VALUES (?, ?)",
            (run.candidate_id, run.model_dump_json()),
        )
    before = database.read_bytes()

    result = snapshot(database, tmp_path, "CAND_DEMO")

    assert result.public_careers.status == "complete"
    assert result.public_careers.records == [own]
    assert result.public_careers.runs == [run]
    assert result.jobs == []
    assert database.read_bytes() == before


def test_source_identity_mismatch_is_invalid_and_never_leaks_records(tmp_path):
    database = tmp_path / "mismatch.sqlite3"
    with source_tables(database) as connection:
        connection.execute(
            "INSERT INTO public_career_records VALUES (?, ?)",
            ("CAND_DEMO", record("CAND_OTHER").model_dump_json()),
        )

    result = snapshot(database, tmp_path, "CAND_DEMO")

    assert result.public_careers.status == "invalid"
    assert result.public_careers.records == []
    assert result.public_careers.runs == []


def test_corrupt_public_record_is_not_treated_as_successful_zero_results(tmp_path):
    database = tmp_path / "corrupt-record.sqlite3"
    with source_tables(database) as connection:
        connection.execute(
            "INSERT INTO public_career_records VALUES (?, ?)", ("CAND_DEMO", "not-json")
        )

    result = snapshot(database, tmp_path, "CAND_DEMO")

    assert result.public_careers.status == "invalid"
    assert result.public_careers.records == []
