from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest

from jobagent.errors import InvalidProviderOutputError
from jobagent.jobs.normalization import JobNormalizer
from jobagent.reasoning.job_matcher import ReasoningJobMatcher
from jobagent.schemas.candidate import Confidence, EvidenceItem, EvidenceType
from jobagent.schemas.common import ContractModel, SourceReference, SourceType
from jobagent.schemas.job_intelligence import (
    RequirementEvidenceMatch,
    RequirementMatchOutcome,
    RequirementMatchSet,
    SourceJobRecord,
)
from jobagent.schemas.jobs import (
    JobRequirement,
    JobRequirementProfile,
    RequirementPriority,
)


def job():
    return JobNormalizer().normalize(
        SourceJobRecord(
            source="mock-alpha",
            source_job_id="alpha-001",
            title="AI Engineer",
            company="Example AI",
            location="Copenhagen",
            jd_raw="Build Python services and production RAG workflows.",
            url="https://jobs.example.test/alpha-001",
            collected_at=datetime(2026, 8, 21, tzinfo=UTC),
        )
    )


def requirement_profile(job_id: str, *, keyword: str = "Python") -> JobRequirementProfile:
    return JobRequirementProfile(
        job_id=job_id,
        requirements=[
            JobRequirement(
                id="REQ_001",
                statement=f"Production {keyword} experience.",
                category="skill",
                priority=RequirementPriority.MUST,
                source_span=f"production {keyword} workflows"
                if keyword == "RAG"
                else "Build Python services",
                keywords=[keyword],
            )
        ],
    )


def evidence(
    evidence_id: str = "EVID_PYTHON",
    *,
    skill: str = "Python",
    confirmed: bool = True,
    confidence: Confidence = Confidence.EXPLICIT,
) -> EvidenceItem:
    return EvidenceItem(
        id=evidence_id,
        type=EvidenceType.SKILL,
        statement=f"Built internal {skill} services.",
        skills=[skill],
        source=SourceReference(type=SourceType.RESUME, reference="RESUME_001:page:1"),
        confidence=confidence,
        user_confirmed=confirmed,
    )


class FakeProvider:
    def __init__(self, output: RequirementMatchSet) -> None:
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


def supported_output(job_id: str, evidence_id: str = "EVID_PYTHON") -> RequirementMatchSet:
    return RequirementMatchSet(
        job_id=job_id,
        candidate_id="CAND_001",
        matches=[
            RequirementEvidenceMatch(
                requirement_id="REQ_001",
                outcome=RequirementMatchOutcome.SUPPORTED,
                evidence_ids=[evidence_id],
                explanation="Confirmed evidence supports the requirement.",
            )
        ],
    )


def test_matcher_uses_typed_prompt_and_marks_admissibility() -> None:
    normalized = job()
    profile = requirement_profile(normalized.id)
    provider = FakeProvider(supported_output(normalized.id))

    result = ReasoningJobMatcher(provider).map(
        normalized,
        profile,
        "CAND_001",
        [evidence()],
    )

    assert result.matches[0].outcome is RequirementMatchOutcome.SUPPORTED
    assert provider.prompt_id == "job.match.evidence.v1"
    assert provider.output_type is RequirementMatchSet
    assert provider.context is not None
    assert provider.context["candidate_id"] == "CAND_001"
    assert provider.context["evidence"][0]["admissible"] is True


@pytest.mark.parametrize(
    "kind",
    ["foreign_candidate", "foreign_requirement", "foreign_evidence", "unconfirmed", "weak"],
)
def test_matcher_rejects_invalid_or_inadmissible_support(kind: str) -> None:
    normalized = job()
    profile = requirement_profile(normalized.id)
    output = supported_output(normalized.id)
    candidate_evidence = [evidence()]
    if kind == "foreign_candidate":
        output = output.model_copy(update={"candidate_id": "CAND_OTHER"})
    elif kind == "foreign_requirement":
        output.matches[0] = output.matches[0].model_copy(update={"requirement_id": "REQ_OTHER"})
    elif kind == "foreign_evidence":
        output.matches[0] = output.matches[0].model_copy(update={"evidence_ids": ["EVID_OTHER"]})
    elif kind == "unconfirmed":
        candidate_evidence = [evidence(confirmed=False)]
    else:
        candidate_evidence = [evidence(confirmed=False, confidence=Confidence.WEAK)]

    with pytest.raises(InvalidProviderOutputError):
        ReasoningJobMatcher(FakeProvider(output)).map(
            normalized,
            profile,
            "CAND_001",
            candidate_evidence,
        )


def test_no_rag_evidence_prevents_supported_rag_match() -> None:
    normalized = job()
    profile = requirement_profile(normalized.id, keyword="RAG")

    with pytest.raises(InvalidProviderOutputError, match="semantic"):
        ReasoningJobMatcher(FakeProvider(supported_output(normalized.id))).map(
            normalized,
            profile,
            "CAND_001",
            [evidence()],
        )
