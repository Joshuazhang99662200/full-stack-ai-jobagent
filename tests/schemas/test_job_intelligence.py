from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from jobagent.schemas.job_intelligence import (
    MatchThresholdPolicy,
    RankedJob,
    RequirementEvidenceMatch,
    RequirementMatchOutcome,
    RequirementMatchSet,
    SourceJobRecord,
)
from jobagent.schemas.jobs import FilterDecision, MatchDecision


def source_job() -> SourceJobRecord:
    return SourceJobRecord(
        source="mock-alpha",
        source_job_id="alpha-001",
        title="Python Engineer",
        company="Example Labs",
        location="Copenhagen",
        salary_text="DKK 600000-720000 year",
        jd_raw="Build Python services and maintain APIs.",
        url="https://example.test/jobs/alpha-001",
        collected_at=datetime(2026, 8, 21, tzinfo=UTC),
    )


def test_source_job_forbids_empty_required_fields() -> None:
    with pytest.raises(ValidationError):
        SourceJobRecord.model_validate({**source_job().model_dump(), "title": ""})

    with pytest.raises(ValidationError):
        SourceJobRecord.model_validate({**source_job().model_dump(), "jd_raw": ""})


def test_supported_requirement_mapping_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        RequirementEvidenceMatch(
            requirement_id="REQ_001",
            outcome=RequirementMatchOutcome.SUPPORTED,
            evidence_ids=[],
            explanation="Candidate has the skill.",
        )


def test_requirement_match_set_requires_unique_requirement_ids() -> None:
    mapping = RequirementEvidenceMatch(
        requirement_id="REQ_001",
        outcome=RequirementMatchOutcome.SUPPORTED,
        evidence_ids=["EVID_001"],
        explanation="Confirmed Python evidence supports the requirement.",
    )

    with pytest.raises(ValidationError, match="unique"):
        RequirementMatchSet(
            job_id="JOB_001",
            candidate_id="CAND_001",
            matches=[mapping, mapping],
        )


def test_match_thresholds_must_descend() -> None:
    policy = MatchThresholdPolicy(strong=0.8, possible=0.6, weak=0.35)
    assert policy.strong > policy.possible > policy.weak

    with pytest.raises(ValidationError):
        MatchThresholdPolicy(strong=0.5, possible=0.6, weak=0.35)


def test_ranked_review_job_cannot_be_application_ready() -> None:
    ranked = RankedJob(
        job_id="JOB_001",
        rank=1,
        filter_decision=FilterDecision.REVIEW,
        match_decision=MatchDecision.STRONG_MATCH,
        overall=0.9,
        must_have_score=1.0,
        application_ready=False,
        explanation="Location requires review.",
    )
    assert not ranked.application_ready

    with pytest.raises(ValidationError):
        RankedJob(
            job_id="JOB_001",
            rank=1,
            filter_decision=FilterDecision.PASS,
            match_decision=MatchDecision.STRONG_MATCH,
            overall=0.9,
            must_have_score=1.0,
            application_ready=True,
            explanation="Still requires later application approval.",
        )
