from jobagent.candidate.readiness import CandidateReadinessService
from jobagent.schemas.candidate import (
    CandidateProfile,
    Confidence,
    EvidenceItem,
    EvidenceType,
    Experience,
    Skill,
    UnknownField,
)
from jobagent.schemas.common import SourceReference, SourceType, TimeRange


def candidate_profile(*, unknown: bool = False) -> CandidateProfile:
    return CandidateProfile(
        id="CAND_001",
        full_name="Ada Lovelace",
        experiences=[
            Experience(
                id="EXP_001",
                company="Analytical Engines",
                title="Engineer",
                time_range=TimeRange(),
                evidence_ids=["EVID_001"],
            )
        ],
        skills=[Skill(name="Python", evidence_ids=["EVID_001"])],
        unknown_fields=(
            [
                UnknownField(
                    path="experiences[0].team_scope",
                    reason="Team scope is unclear.",
                    target_role_relevance=0.8,
                )
            ]
            if unknown
            else []
        ),
    )


def candidate_evidence(*, confirmed: bool = False) -> EvidenceItem:
    return EvidenceItem(
        id="EVID_001",
        type=EvidenceType.EXPERIENCE,
        statement="Built internal Python tooling.",
        skills=["Python"],
        source=SourceReference(type=SourceType.RESUME, reference="RESUME_001:page:1"),
        confidence=Confidence.EXPLICIT,
        user_confirmed=confirmed,
    )


def test_empty_candidate_status_is_descriptive_and_bounded() -> None:
    status = CandidateReadinessService().evaluate(CandidateProfile(id="CAND_001"), [])

    assert status.candidate_id == "CAND_001"
    assert status.readiness.profile_completeness == 0
    assert 0 <= status.readiness.target_role_readiness <= 1
    assert status.open_gap_count == 3
    assert status.readiness.confirmed_evidence_count == 0


def test_confirmation_improves_readiness_without_changing_profile() -> None:
    service = CandidateReadinessService()
    profile = candidate_profile()

    draft_status = service.evaluate(
        profile,
        [candidate_evidence()],
        target_role="Python Engineer",
    )
    confirmed_status = service.evaluate(
        profile,
        [candidate_evidence(confirmed=True)],
        target_role="Python Engineer",
    )

    assert draft_status.unconfirmed_evidence_count == 1
    assert confirmed_status.unconfirmed_evidence_count == 0
    assert confirmed_status.readiness.confirmed_evidence_count == 1
    assert (
        confirmed_status.readiness.target_role_readiness
        > draft_status.readiness.target_role_readiness
    )


def test_explicit_unknowns_reduce_completeness_and_remain_open_gaps() -> None:
    service = CandidateReadinessService()
    evidence = [candidate_evidence(confirmed=True)]

    known = service.evaluate(candidate_profile(), evidence)
    unknown = service.evaluate(candidate_profile(unknown=True), evidence)

    assert (
        unknown.readiness.profile_completeness < known.readiness.profile_completeness
    )
    assert unknown.open_gap_count > known.open_gap_count
