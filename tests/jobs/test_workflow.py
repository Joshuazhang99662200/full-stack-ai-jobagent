from datetime import UTC, datetime
from pathlib import Path

import pytest

from jobagent.errors import JobNotFoundError
from jobagent.jobs.deduplication import JobDeduplicator
from jobagent.jobs.hard_filter import HardFilterEngine
from jobagent.jobs.matching import MatchAggregator
from jobagent.jobs.normalization import JobNormalizer
from jobagent.jobs.ranking import JobRanker
from jobagent.jobs.workflow import JobIntelligenceWorkflow
from jobagent.schemas.candidate import CandidateProfile, Confidence, EvidenceItem, EvidenceType
from jobagent.schemas.common import SourceReference, SourceType
from jobagent.schemas.job_intelligence import (
    CandidateFilterContext,
    JobIntelligencePolicies,
    JobSearchQuery,
    RequirementEvidenceMatch,
    RequirementMatchOutcome,
    RequirementMatchSet,
    SourceJobRecord,
)
from jobagent.schemas.jobs import (
    FilterDecision,
    JobRequirement,
    JobRequirementProfile,
    RequirementPriority,
)
from jobagent.storage.candidate_repository import SqliteCandidateRepository
from jobagent.storage.database import Database
from jobagent.storage.job_repository import SqliteJobRepository


def record(source_job_id: str, title: str) -> SourceJobRecord:
    return SourceJobRecord(
        source="mock-alpha",
        source_job_id=source_job_id,
        title=title,
        company="Example Labs",
        location="Copenhagen",
        jd_raw=f"Use Python in the {title} role.",
        url=f"https://jobs.example.test/{source_job_id}",
        published_at=datetime(2026, 8, 20, tzinfo=UTC),
        collected_at=datetime(2026, 8, 21, tzinfo=UTC),
    )


class Source:
    def search(self, query: JobSearchQuery) -> list[SourceJobRecord]:
        return [record("alpha-001", "Python Engineer"), record("alpha-002", "Sales Manager")]

    def fetch_job(self, source_job_id: str) -> SourceJobRecord:
        raise AssertionError("workflow search records are already complete")

    def get_recruiter(self, source_job_id: str):
        return None


class FailingSource(Source):
    def search(self, query: JobSearchQuery) -> list[SourceJobRecord]:
        raise JobNotFoundError("source unavailable")


class Extractor:
    def extract(self, job) -> JobRequirementProfile:
        return JobRequirementProfile(
            job_id=job.id,
            requirements=[
                JobRequirement(
                    id="REQ_PYTHON",
                    statement="Use Python",
                    category="skill",
                    priority=RequirementPriority.MUST,
                    source_span="Use Python",
                    keywords=["Python"],
                )
            ],
            must_have=["Use Python"],
            skills=["Python"],
        )


class Matcher:
    def __init__(self) -> None:
        self.job_ids: list[str] = []

    def map(self, job, requirements, candidate_id, evidence) -> RequirementMatchSet:
        self.job_ids.append(job.id)
        return RequirementMatchSet(
            job_id=job.id,
            candidate_id=candidate_id,
            matches=[
                RequirementEvidenceMatch(
                    requirement_id="REQ_PYTHON",
                    outcome=RequirementMatchOutcome.SUPPORTED,
                    evidence_ids=["EVID_PYTHON"],
                    explanation="Confirmed Python evidence.",
                )
            ],
        )


def repositories(path: Path):
    database = Database(path)
    database.migrate()
    candidate_repository = SqliteCandidateRepository(database)
    candidate_repository.save_profile(CandidateProfile(id="CAND_001"))
    candidate_repository.upsert_evidence(
        "CAND_001",
        EvidenceItem(
            id="EVID_PYTHON",
            type=EvidenceType.SKILL,
            statement="Built Python services.",
            skills=["Python"],
            source=SourceReference(type=SourceType.RESUME, reference="RESUME_001:page:1"),
            confidence=Confidence.EXPLICIT,
            user_confirmed=True,
        ),
    )
    return candidate_repository, SqliteJobRepository(database)


def workflow(source, matcher, candidate_repository, job_repository):
    return JobIntelligenceWorkflow(
        source=source,
        normalizer=JobNormalizer(),
        deduplicator=JobDeduplicator(),
        requirement_extractor=Extractor(),
        hard_filter=HardFilterEngine(),
        matcher=matcher,
        aggregator=MatchAggregator(),
        ranker=JobRanker(),
        candidate_repository=candidate_repository,
        job_repository=job_repository,
    )


def test_workflow_never_matches_rejected_jobs(tmp_path: Path) -> None:
    candidate_repository, job_repository = repositories(tmp_path / "jobagent.sqlite3")
    matcher = Matcher()

    result = workflow(Source(), matcher, candidate_repository, job_repository).run(
        JobSearchQuery(query=""),
        "CAND_001",
        CandidateFilterContext(candidate_id="CAND_001", excluded_role_terms=["sales"]),
        JobIntelligencePolicies(),
    )

    assert len(result.normalized_jobs) == 2
    assert sorted(item.decision for item in result.filter_results.values()) == [
        FilterDecision.PASS,
        FilterDecision.REJECT,
    ]
    assert len(matcher.job_ids) == 1
    assert len(result.matches) == 1
    assert len(result.ranked_jobs) == 1
    assert len(job_repository.list_jobs()) == 2


def test_source_failure_creates_no_partial_job_records(tmp_path: Path) -> None:
    candidate_repository, job_repository = repositories(tmp_path / "jobagent.sqlite3")

    with pytest.raises(JobNotFoundError):
        workflow(
            FailingSource(),
            Matcher(),
            candidate_repository,
            job_repository,
        ).run(
            JobSearchQuery(query="Python"),
            "CAND_001",
            CandidateFilterContext(candidate_id="CAND_001"),
            JobIntelligencePolicies(),
        )

    assert job_repository.list_jobs() == []
