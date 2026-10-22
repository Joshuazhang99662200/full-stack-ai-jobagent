import pytest

from jobagent.errors import ContractValidationError
from jobagent.optimizer.base_resume import BaseResumeBuilder
from jobagent.schemas.candidate import (
    Confidence,
    EvidenceItem,
    EvidenceType,
)
from jobagent.schemas.common import SourceReference, SourceType


def evidence(
    identifier: str,
    *,
    kind: EvidenceType = EvidenceType.EXPERIENCE,
    statement: str = "Built and operated Python services.",
    confirmed: bool = True,
) -> EvidenceItem:
    return EvidenceItem(
        id=identifier,
        type=kind,
        statement=statement,
        source=SourceReference(type=SourceType.RESUME, reference="RESUME_001:page:1"),
        confidence=Confidence.EXPLICIT,
        user_confirmed=confirmed,
    )


def test_each_confirmed_evidence_becomes_one_verbatim_item() -> None:
    document = BaseResumeBuilder().build(
        candidate_id="CAND_001",
        evidence=[evidence("EVID_EXP_APIGW")],
        language="en",
    )

    assert len(document.items) == 1
    item = document.items[0]
    assert item.text == "Built and operated Python services."
    assert item.evidence_ids == ["EVID_EXP_APIGW"]


def test_item_id_is_derived_deterministically_from_the_evidence_id() -> None:
    document = BaseResumeBuilder().build(
        candidate_id="CAND_001",
        evidence=[evidence("EVID_EXP_APIGW")],
        language="en",
    )

    assert document.items[0].id == "ITEM_EXP_APIGW"


def test_unconfirmed_evidence_never_reaches_the_base_resume() -> None:
    """Unconfirmed evidence cannot support a claim, so it cannot seed one either."""
    document = BaseResumeBuilder().build(
        candidate_id="CAND_001",
        evidence=[evidence("EVID_KEPT"), evidence("EVID_DROPPED", confirmed=False)],
        language="en",
    )

    assert [item.evidence_ids[0] for item in document.items] == ["EVID_KEPT"]


def test_refuses_to_emit_rather_than_emit_an_empty_resume() -> None:
    with pytest.raises(ContractValidationError):
        BaseResumeBuilder().build(
            candidate_id="CAND_001",
            evidence=[evidence("EVID_DRAFT", confirmed=False)],
            language="en",
        )


def test_evidence_type_selects_the_section() -> None:
    document = BaseResumeBuilder().build(
        candidate_id="CAND_001",
        evidence=[
            evidence("EVID_A", kind=EvidenceType.EXPERIENCE),
            evidence("EVID_B", kind=EvidenceType.SKILL),
            evidence("EVID_C", kind=EvidenceType.EDUCATION),
        ],
        language="en",
    )

    assert [item.section for item in document.items] == ["experience", "skills", "education"]


def test_digest_is_stable_for_the_same_evidence_and_moves_with_it() -> None:
    builder = BaseResumeBuilder()
    first = builder.build(
        candidate_id="CAND_001", evidence=[evidence("EVID_A")], language="en"
    )
    same = builder.build(candidate_id="CAND_001", evidence=[evidence("EVID_A")], language="en")
    changed = builder.build(
        candidate_id="CAND_001",
        evidence=[evidence("EVID_A", statement="A different confirmed statement.")],
        language="en",
    )

    assert first.source_digest == same.source_digest
    assert first.source_digest != changed.source_digest
    assert first.source_digest.startswith("sha256:")
