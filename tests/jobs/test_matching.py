from jobagent.errors import MissingEvidenceError
from jobagent.jobs.matching import MatchAggregator, admissible_evidence
from jobagent.schemas.candidate import Confidence, EvidenceItem, EvidenceType
from jobagent.schemas.common import SourceReference, SourceType
from jobagent.schemas.job_intelligence import (
    MatchThresholdPolicy,
    RequirementEvidenceMatch,
    RequirementMatchOutcome,
    RequirementMatchSet,
)
from jobagent.schemas.jobs import (
    JobRequirement,
    JobRequirementProfile,
    MatchDecision,
    RequirementPriority,
)


def evidence(evidence_id: str, *, confirmed: bool = True) -> EvidenceItem:
    return EvidenceItem(
        id=evidence_id,
        type=EvidenceType.SKILL,
        statement="Built Python API services.",
        skills=["Python", "API"],
        source=SourceReference(type=SourceType.RESUME, reference="RESUME_001:page:1"),
        confidence=Confidence.EXPLICIT,
        user_confirmed=confirmed,
    )


def requirements() -> JobRequirementProfile:
    return JobRequirementProfile(
        job_id="JOB_001",
        requirements=[
            JobRequirement(
                id="REQ_MUST",
                statement="Python API experience",
                category="skill",
                priority=RequirementPriority.MUST,
                source_span="Python API experience",
                keywords=["Python", "API"],
            ),
            JobRequirement(
                id="REQ_PREFERRED",
                statement="AWS experience",
                category="skill",
                priority=RequirementPriority.PREFERRED,
                source_span="AWS experience",
                keywords=["AWS"],
            ),
        ],
    )


def mappings(preferred: RequirementMatchOutcome) -> RequirementMatchSet:
    return RequirementMatchSet(
        job_id="JOB_001",
        candidate_id="CAND_001",
        matches=[
            RequirementEvidenceMatch(
                requirement_id="REQ_MUST",
                outcome=RequirementMatchOutcome.SUPPORTED,
                evidence_ids=["EVID_001"],
                explanation="Confirmed Python evidence.",
            ),
            RequirementEvidenceMatch(
                requirement_id="REQ_PREFERRED",
                outcome=preferred,
                evidence_ids=[],
                explanation="No AWS evidence.",
            ),
        ],
    )


def test_admissibility_excludes_unconfirmed_and_weak_evidence() -> None:
    weak = evidence("EVID_WEAK", confirmed=False).model_copy(update={"confidence": Confidence.WEAK})

    result = admissible_evidence(
        [evidence("EVID_CONFIRMED"), evidence("EVID_DRAFT", confirmed=False), weak]
    )

    assert [item.id for item in result] == ["EVID_CONFIRMED"]


def test_aggregator_computes_scores_and_explanatory_lanes() -> None:
    result = MatchAggregator().aggregate(
        requirements(),
        mappings(RequirementMatchOutcome.MISSING),
        [evidence("EVID_001")],
        MatchThresholdPolicy(),
    )

    assert result.overall == 0.6
    assert result.decision is MatchDecision.POSSIBLE_MATCH
    assert result.strengths == ["Python API experience"]
    assert result.partial_matches == ["Missing preferred: AWS experience"]
    assert result.hard_gaps == []
    assert result.evidence_ids == ["EVID_001"]


def test_missing_must_requirement_is_hard_gap() -> None:
    mapping_set = mappings(RequirementMatchOutcome.MISSING)
    mapping_set.matches[0] = mapping_set.matches[0].model_copy(
        update={
            "outcome": RequirementMatchOutcome.MISSING,
            "evidence_ids": [],
            "explanation": "No Python evidence.",
        }
    )
    mapping_set.matches[1] = mapping_set.matches[1].model_copy(
        update={
            "outcome": RequirementMatchOutcome.SUPPORTED,
            "evidence_ids": ["EVID_001"],
            "explanation": "Confirmed evidence supports AWS.",
        }
    )

    result = MatchAggregator().aggregate(
        requirements(),
        mapping_set,
        [evidence("EVID_001")],
        MatchThresholdPolicy(),
    )

    assert result.hard_gaps == ["Python API experience"]
    assert result.decision is MatchDecision.WEAK_MATCH


def test_aggregator_rejects_nonadmissible_cited_evidence() -> None:
    try:
        MatchAggregator().aggregate(
            requirements(),
            mappings(RequirementMatchOutcome.MISSING),
            [evidence("EVID_001", confirmed=False)],
            MatchThresholdPolicy(),
        )
    except MissingEvidenceError as error:
        assert error.code == "MISSING_EVIDENCE"
    else:
        raise AssertionError("nonadmissible support must be rejected")
