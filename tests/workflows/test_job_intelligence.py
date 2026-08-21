from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jobagent.connectors.mock import MockJobSource
from jobagent.jobs.deduplication import JobDeduplicator
from jobagent.jobs.hard_filter import HardFilterEngine
from jobagent.jobs.matching import MatchAggregator
from jobagent.jobs.normalization import JobNormalizer
from jobagent.jobs.ranking import JobRanker
from jobagent.jobs.workflow import JobIntelligenceWorkflow
from jobagent.reasoning.job_matcher import ReasoningJobMatcher
from jobagent.reasoning.job_requirements import ReasoningJobRequirementExtractor
from jobagent.schemas.candidate import CandidateProfile, Confidence, EvidenceItem, EvidenceType
from jobagent.schemas.common import SourceReference, SourceType
from jobagent.schemas.job_intelligence import (
    CandidateFilterContext,
    JobIntelligencePolicies,
    JobSearchQuery,
)
from jobagent.schemas.jobs import FilterDecision
from jobagent.storage.candidate_repository import SqliteCandidateRepository
from jobagent.storage.database import Database
from jobagent.storage.job_repository import SqliteJobRepository

FIXTURE = Path("src/jobagent/connectors/fixtures/jobs.json")


class ReviewedProvider:
    def __init__(self) -> None:
        self.matched_job_ids: list[str] = []

    def generate(self, *, prompt_id: str, context: Mapping[str, Any], output_type):
        title = str(context.get("title", ""))
        job_id = str(context["job_id"])
        if prompt_id == "job.requirements.extract.v1":
            if "Sales" in title:
                statement = "Lead enterprise sales"
                keyword = "sales"
            elif "Machine Learning" in title:
                statement = "Develop machine learning pipelines"
                keyword = "machine learning"
            else:
                statement = "Build Python API services"
                keyword = "Python"
            return output_type.model_validate(
                {
                    "job_id": job_id,
                    "requirements": [
                        {
                            "id": "REQ_PRIMARY",
                            "statement": statement,
                            "category": "skill",
                            "priority": "must",
                            "source_span": statement,
                            "keywords": [keyword],
                        }
                    ],
                    "must_have": [statement],
                    "skills": [keyword],
                }
            )

        self.matched_job_ids.append(job_id)
        requirements = context["requirements"]
        supported = isinstance(requirements, list) and any(
            "Python" in item.get("keywords", []) for item in requirements if isinstance(item, dict)
        )
        return output_type.model_validate(
            {
                "job_id": job_id,
                "candidate_id": context["candidate_id"],
                "matches": [
                    {
                        "requirement_id": "REQ_PRIMARY",
                        "outcome": "supported" if supported else "uncertain",
                        "evidence_ids": ["EVID_PYTHON"] if supported else [],
                        "explanation": (
                            "Confirmed Python evidence."
                            if supported
                            else "No confirmed matching evidence."
                        ),
                    }
                ],
            }
        )


def test_offline_job_intelligence_vertical_flow(tmp_path: Path) -> None:
    database = Database(tmp_path / "jobagent.sqlite3")
    database.migrate()
    candidate_repository = SqliteCandidateRepository(database)
    job_repository = SqliteJobRepository(database)
    candidate_repository.save_profile(CandidateProfile(id="CAND_001"))
    candidate_repository.upsert_evidence(
        "CAND_001",
        EvidenceItem(
            id="EVID_PYTHON",
            type=EvidenceType.SKILL,
            statement="Built production Python services.",
            skills=["Python"],
            source=SourceReference(type=SourceType.RESUME, reference="RESUME_001:page:1"),
            confidence=Confidence.EXPLICIT,
            user_confirmed=True,
        ),
    )
    provider = ReviewedProvider()
    workflow = JobIntelligenceWorkflow(
        source=MockJobSource.from_path(FIXTURE),
        normalizer=JobNormalizer(),
        deduplicator=JobDeduplicator(),
        requirement_extractor=ReasoningJobRequirementExtractor(provider),
        hard_filter=HardFilterEngine(),
        matcher=ReasoningJobMatcher(provider),
        aggregator=MatchAggregator(),
        ranker=JobRanker(),
        candidate_repository=candidate_repository,
        job_repository=job_repository,
    )

    result = workflow.run(
        JobSearchQuery(),
        "CAND_001",
        CandidateFilterContext(
            candidate_id="CAND_001",
            allowed_locations=["Copenhagen"],
            remote_allowed=None,
            excluded_role_terms=["sales"],
        ),
        JobIntelligencePolicies(),
    )

    assert len(result.normalized_jobs) == 3
    python_job = next(job for job in result.normalized_jobs if "Python Platform" in job.title)
    sales_job = next(job for job in result.normalized_jobs if "Sales" in job.title)
    assert {item.source_id for item in python_job.provenance} == {"alpha-001", "beta-991"}
    decisions = [item.decision for item in result.filter_results.values()]
    assert decisions.count(FilterDecision.PASS) == 1
    assert decisions.count(FilterDecision.REVIEW) == 1
    assert decisions.count(FilterDecision.REJECT) == 1
    assert sales_job.id not in provider.matched_job_ids
    assert len(result.matches) == 2
    assert result.matches[python_job.id].evidence_ids == ["EVID_PYTHON"]
    assert [item.filter_decision for item in result.ranked_jobs] == [
        FilterDecision.PASS,
        FilterDecision.REVIEW,
    ]
    assert all(item.application_ready is False for item in result.ranked_jobs)

    assert len(job_repository.list_jobs()) == 3
    assert job_repository.get_job(python_job.id) == python_job
    assert job_repository.get_requirements(python_job.id) is not None
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM hard_filter_results").fetchone()[0] == 3
        assert connection.execute("SELECT COUNT(*) FROM job_matches").fetchone()[0] == 2
