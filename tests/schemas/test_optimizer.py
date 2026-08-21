import pytest
from pydantic import ValidationError

from jobagent.schemas.optimizer import ClaimRecord, VerificationStatus


def test_substantive_claim_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        ClaimRecord(
            claim_id="CLAIM_001",
            resume_item_id="ITEM_001",
            text="Built a production RAG platform.",
            claim_type="experience",
            evidence_ids=[],
            requirement_ids=["REQ_001"],
            verification_status=VerificationStatus.UNSUPPORTED,
        )


def test_supported_claim_accepts_evidence() -> None:
    claim = ClaimRecord(
        claim_id="CLAIM_002",
        resume_item_id="ITEM_002",
        text="Reduced review time by 30%.",
        claim_type="achievement",
        evidence_ids=["EVID_001"],
        requirement_ids=["REQ_002"],
        verification_status=VerificationStatus.SUPPORTED,
    )
    assert claim.evidence_ids == ["EVID_001"]
