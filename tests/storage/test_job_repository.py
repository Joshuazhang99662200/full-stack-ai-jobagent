import sqlite3
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

import pytest

from jobagent.errors import StorageError
from jobagent.jobs.normalization import JobNormalizer
from jobagent.schemas.candidate import CandidateProfile
from jobagent.schemas.job_intelligence import SourceJobRecord
from jobagent.schemas.jobs import (
    FilterDecision,
    HardFilterResult,
    JobRequirement,
    JobRequirementProfile,
    MatchDecision,
    MatchResult,
    RequirementPriority,
)
from jobagent.storage.candidate_repository import SqliteCandidateRepository
from jobagent.storage.database import Database
from jobagent.storage.job_repository import SqliteJobRepository


def normalized_job(source_job_id: str = "alpha-001"):
    return JobNormalizer().normalize(
        SourceJobRecord(
            source="mock-alpha",
            source_job_id=source_job_id,
            title="Python Engineer",
            company="Example Labs",
            location="Copenhagen",
            jd_raw="Build Python API services.",
            url=f"https://jobs.example.test/{source_job_id}",
            collected_at=datetime(2026, 8, 21, tzinfo=UTC),
        )
    )


def requirements(job_id: str) -> JobRequirementProfile:
    return JobRequirementProfile(
        job_id=job_id,
        requirements=[
            JobRequirement(
                id="REQ_001",
                statement="Build Python API services.",
                category="skill",
                priority=RequirementPriority.MUST,
                source_span="Build Python API services.",
                keywords=["Python", "API"],
            )
        ],
        must_have=["Build Python API services."],
        skills=["Python"],
    )


def repository_at(path: Path) -> tuple[Database, SqliteJobRepository]:
    database = Database(path)
    database.migrate()
    return database, SqliteJobRepository(database)


def test_v1_database_upgrades_to_v2_without_losing_candidate(tmp_path: Path) -> None:
    path = tmp_path / "jobagent.sqlite3"
    migration = (
        resources.files("jobagent.storage.migrations")
        .joinpath("0001_candidate.sql")
        .read_text(encoding="utf-8")
    )
    with sqlite3.connect(path) as connection:
        connection.executescript(migration)
        profile = CandidateProfile(id="CAND_001", full_name="Ada Lovelace")
        connection.execute(
            """
            INSERT INTO candidate_profiles (candidate_id, profile_json, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (profile.id, profile.model_dump_json(), "now", "now"),
        )

    database = Database(path)
    database.migrate()

    assert SqliteCandidateRepository(database).get_profile("CAND_001") == profile
    with database.connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        assert (
            connection.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='normalized_jobs'"
            ).fetchone()[0]
            == 1
        )


def test_job_and_provenance_round_trip(tmp_path: Path) -> None:
    database, repository = repository_at(tmp_path / "jobagent.sqlite3")
    job = normalized_job()

    repository.save_job(job)

    assert repository.get_job(job.id) == job
    assert repository.list_jobs() == [job]
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT source, source_id FROM job_provenance WHERE job_id = ?",
            (job.id,),
        ).fetchall()
    assert [(row["source"], row["source_id"]) for row in rows] == [("mock-alpha", "alpha-001")]


def test_requirements_filter_and_match_round_trip_with_digest_keys(tmp_path: Path) -> None:
    database, repository = repository_at(tmp_path / "jobagent.sqlite3")
    candidate_repository = SqliteCandidateRepository(database)
    candidate_repository.save_profile(CandidateProfile(id="CAND_001"))
    job = normalized_job()
    repository.save_job(job)
    profile = requirements(job.id)
    filter_result = HardFilterResult(decision=FilterDecision.PASS)
    match_result = MatchResult(
        overall=0.8,
        decision=MatchDecision.STRONG_MATCH,
        strengths=["Confirmed Python API experience."],
        evidence_ids=["EVID_001"],
    )

    requirements_digest = repository.save_requirements(profile)
    repository.save_filter_result("CAND_001", job.id, "sha256:filter", filter_result)
    repository.save_match(
        "CAND_001",
        job.id,
        evidence_digest="sha256:evidence",
        requirements_digest=requirements_digest,
        policy_digest="sha256:match-policy",
        result=match_result,
    )

    assert repository.get_requirements(job.id) == profile
    assert repository.get_filter_result("CAND_001", job.id, "sha256:filter") == filter_result
    assert (
        repository.get_match(
            "CAND_001",
            job.id,
            evidence_digest="sha256:evidence",
            requirements_digest=requirements_digest,
            policy_digest="sha256:match-policy",
        )
        == match_result
    )
    assert (
        repository.get_match(
            "CAND_001",
            job.id,
            evidence_digest="sha256:stale",
            requirements_digest=requirements_digest,
            policy_digest="sha256:match-policy",
        )
        is None
    )


def test_save_job_rolls_back_job_and_provenance_together(tmp_path: Path) -> None:
    _, repository = repository_at(tmp_path / "jobagent.sqlite3")
    original = normalized_job()
    repository.save_job(original)
    duplicate_provenance = original.model_copy(
        update={
            "title": "Mutated title",
            "provenance": [original.provenance[0], original.provenance[0]],
        }
    )

    with pytest.raises(StorageError, match="save normalized job"):
        repository.save_job(duplicate_provenance)

    assert repository.get_job(original.id) == original
