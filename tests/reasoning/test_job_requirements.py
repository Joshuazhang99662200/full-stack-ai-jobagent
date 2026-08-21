from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest

from jobagent.errors import InvalidProviderOutputError
from jobagent.jobs.normalization import JobNormalizer
from jobagent.reasoning.job_requirements import ReasoningJobRequirementExtractor
from jobagent.schemas.common import ContractModel
from jobagent.schemas.job_intelligence import SourceJobRecord
from jobagent.schemas.jobs import (
    JobRequirement,
    JobRequirementProfile,
    RequirementPriority,
)


def normalized_job():
    return JobNormalizer().normalize(
        SourceJobRecord(
            source="mock-alpha",
            source_job_id="alpha-001",
            title="Python Engineer",
            company="Example Labs",
            location="Copenhagen",
            jd_raw="Build Python API services. Danish is preferred.",
            url="https://jobs.example.test/alpha-001",
            collected_at=datetime(2026, 8, 21, tzinfo=UTC),
        )
    )


def requirement(
    requirement_id: str = "REQ_001",
    *,
    source_span: str = "Build Python API services.",
) -> JobRequirement:
    return JobRequirement(
        id=requirement_id,
        statement="Build Python API services.",
        category="skill",
        priority=RequirementPriority.MUST,
        source_span=source_span,
        keywords=["Python", "API"],
    )


def valid_profile(job_id: str) -> JobRequirementProfile:
    return JobRequirementProfile(
        job_id=job_id,
        requirements=[requirement()],
        must_have=["Build Python API services."],
        skills=["Build Python API services."],
    )


class FakeProvider:
    def __init__(self, output: JobRequirementProfile) -> None:
        self.output = output
        self.prompt_id: str | None = None
        self.context: Mapping[str, Any] | None = None
        self.output_type: type[ContractModel] | None = None

    def generate(
        self,
        *,
        prompt_id: str,
        context: Mapping[str, Any],
        output_type: type[ContractModel],
    ) -> Any:
        self.prompt_id = prompt_id
        self.context = context
        self.output_type = output_type
        return self.output


def test_requirement_extractor_uses_typed_minimum_job_context() -> None:
    job = normalized_job()
    provider = FakeProvider(valid_profile(job.id))

    result = ReasoningJobRequirementExtractor(provider).extract(job)

    assert result.job_id == job.id
    assert provider.prompt_id == "job.requirements.extract.v1"
    assert provider.output_type is JobRequirementProfile
    assert provider.context == {
        "job_id": job.id,
        "title": "Python Engineer",
        "company": "Example Labs",
        "location": "Copenhagen",
        "jd_raw": "Build Python API services. Danish is preferred.",
    }


@pytest.mark.parametrize("invalid_kind", ["foreign_job", "duplicate", "fake_span", "aggregate"])
def test_requirement_extractor_rejects_invalid_provider_output(invalid_kind: str) -> None:
    job = normalized_job()
    profile = valid_profile(job.id)
    if invalid_kind == "foreign_job":
        profile = profile.model_copy(update={"job_id": "JOB_OTHER"})
    elif invalid_kind == "duplicate":
        profile = profile.model_copy(update={"requirements": [requirement(), requirement()]})
    elif invalid_kind == "fake_span":
        profile = profile.model_copy(
            update={"requirements": [requirement(source_span="Lead a team of 50.")]}
        )
    else:
        profile = profile.model_copy(update={"nice_to_have": ["Kubernetes production ownership"]})

    with pytest.raises(InvalidProviderOutputError):
        ReasoningJobRequirementExtractor(FakeProvider(profile)).extract(job)
