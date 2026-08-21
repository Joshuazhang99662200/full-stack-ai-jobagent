from jobagent.candidate.gaps import GapDetector
from jobagent.schemas.candidate import (
    CandidateProfile,
    Confidence,
    EvidenceItem,
    EvidenceType,
    Experience,
    GapPriority,
    Skill,
)
from jobagent.schemas.common import SourceReference, SourceType, TimeRange


def weak_evidence(evidence_id: str, skill: str) -> EvidenceItem:
    return EvidenceItem(
        id=evidence_id,
        type=EvidenceType.SKILL,
        statement=f"May have used {skill}.",
        skills=[skill],
        source=SourceReference(type=SourceType.RESUME, reference="RESUME_001:page:1"),
        confidence=Confidence.WEAK,
    )


def test_empty_profile_exposes_material_gaps() -> None:
    gaps = GapDetector().detect(CandidateProfile(id="CAND_001"), [])

    assert [gap.id for gap in gaps] == [
        "GAP_EXPERIENCE",
        "GAP_SKILLS",
        "GAP_FULL_NAME",
    ]
    assert gaps[0].priority is GapPriority.HIGH


def test_target_role_relevance_prioritizes_related_weak_evidence() -> None:
    profile = CandidateProfile(
        id="CAND_001",
        full_name="Ada Lovelace",
        experiences=[
            Experience(
                id="EXP_001",
                company="Analytical Engines",
                title="Engineer",
                time_range=TimeRange(),
            )
        ],
        skills=[Skill(name="Python"), Skill(name="Sales")],
    )
    evidence = [
        weak_evidence("EVID_PYTHON", "Python"),
        weak_evidence("EVID_SALES", "Sales"),
    ]

    gaps = GapDetector().detect(profile, evidence, target_role="Python Engineer")

    weak_gaps = [gap for gap in gaps if gap.field_path.startswith("evidence[")]
    assert [gap.id for gap in weak_gaps] == ["GAP_EVID_PYTHON", "GAP_EVID_SALES"]
    assert weak_gaps[0].priority is GapPriority.HIGH
    assert weak_gaps[1].priority is GapPriority.MEDIUM
    assert weak_gaps[0].target_role == "Python Engineer"


def test_confirmed_evidence_does_not_create_weak_claim_gap() -> None:
    item = weak_evidence("EVID_PYTHON", "Python").model_copy(
        update={"confidence": Confidence.EXPLICIT, "user_confirmed": True}
    )
    profile = CandidateProfile(
        id="CAND_001",
        full_name="Ada Lovelace",
        experiences=[
            Experience(
                id="EXP_001",
                company="Analytical Engines",
                title="Engineer",
                time_range=TimeRange(),
            )
        ],
        skills=[Skill(name="Python", evidence_ids=["EVID_PYTHON"])],
    )

    gaps = GapDetector().detect(profile, [item], target_role="Python Engineer")

    assert all(gap.id != "GAP_EVID_PYTHON" for gap in gaps)
