import pytest
from pydantic import ValidationError

from jobagent.schemas.candidate import Confidence, EvidenceItem, EvidenceType
from jobagent.schemas.common import SourceReference, SourceType


def test_evidence_requires_statement_and_source() -> None:
    item = EvidenceItem(
        id="EVID_001",
        type=EvidenceType.ACHIEVEMENT,
        statement="Reduced review time by 30%.",
        source=SourceReference(type=SourceType.RESUME, reference="page:1"),
        confidence=Confidence.EXPLICIT,
        user_confirmed=True,
    )
    assert item.id == "EVID_001"


def test_confirmed_evidence_cannot_be_weak() -> None:
    with pytest.raises(ValidationError):
        EvidenceItem(
            id="EVID_002",
            type=EvidenceType.SKILL,
            statement="May know RAG.",
            source=SourceReference(type=SourceType.RESUME, reference="page:2"),
            confidence=Confidence.WEAK,
            user_confirmed=True,
        )
