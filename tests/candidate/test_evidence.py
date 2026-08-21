from pathlib import Path

import pytest

from jobagent.candidate.evidence import CandidateEvidenceService
from jobagent.errors import MissingEvidenceError, PolicyRejectionError
from jobagent.schemas.candidate import (
    CandidateProfile,
    Confidence,
    EvidenceItem,
    EvidenceType,
)
from jobagent.schemas.common import SourceReference, SourceType
from jobagent.storage.candidate_repository import SqliteCandidateRepository
from jobagent.storage.database import Database


def service_at(path: Path) -> CandidateEvidenceService:
    database = Database(path)
    database.migrate()
    repository = SqliteCandidateRepository(database)
    repository.save_profile(CandidateProfile(id="CAND_001"))
    repository.save_profile(CandidateProfile(id="CAND_002"))
    return CandidateEvidenceService(repository)


def evidence(
    evidence_id: str = "EVID_001",
    *,
    confidence: Confidence = Confidence.EXPLICIT,
    confirmed: bool = False,
) -> EvidenceItem:
    return EvidenceItem(
        id=evidence_id,
        type=EvidenceType.EXPERIENCE,
        statement="Built internal tooling.",
        source=SourceReference(type=SourceType.RESUME, reference="RESUME_001:page:1"),
        confidence=confidence,
        user_confirmed=confirmed,
    )


def test_draft_requires_explicit_confirmation(tmp_path: Path) -> None:
    service = service_at(tmp_path / "candidate.sqlite3")
    draft = evidence()

    service.add_draft("CAND_001", draft)
    stored = service.get("CAND_001", "EVID_001")
    confirmed = service.confirm("CAND_001", "EVID_001")

    assert stored is not None and not stored.user_confirmed
    assert confirmed.user_confirmed
    assert service.get("CAND_001", "EVID_001") == confirmed


def test_add_draft_rejects_preconfirmed_input(tmp_path: Path) -> None:
    service = service_at(tmp_path / "candidate.sqlite3")

    with pytest.raises(PolicyRejectionError, match="already confirmed"):
        service.add_draft("CAND_001", evidence(confirmed=True))


def test_weak_evidence_cannot_be_confirmed(tmp_path: Path) -> None:
    service = service_at(tmp_path / "candidate.sqlite3")
    service.add_draft("CAND_001", evidence(confidence=Confidence.WEAK))

    with pytest.raises(PolicyRejectionError, match="Weak evidence"):
        service.confirm("CAND_001", "EVID_001")


def test_unknown_or_cross_candidate_evidence_is_not_visible(tmp_path: Path) -> None:
    service = service_at(tmp_path / "candidate.sqlite3")
    service.add_draft("CAND_001", evidence())

    with pytest.raises(MissingEvidenceError):
        service.confirm("CAND_002", "EVID_001")
    with pytest.raises(MissingEvidenceError):
        service.confirm("CAND_001", "EVID_MISSING")


def test_user_edit_preserves_identity_but_requires_reconfirmation(tmp_path: Path) -> None:
    service = service_at(tmp_path / "candidate.sqlite3")
    service.add_draft("CAND_001", evidence())
    service.confirm("CAND_001", "EVID_001")

    edited = service.replace_with_user_edit(
        "CAND_001",
        "EVID_001",
        "Built internal tooling used by five teams.",
    )

    assert edited.id == "EVID_001"
    assert edited.statement == "Built internal tooling used by five teams."
    assert edited.source.type is SourceType.USER_EDIT
    assert edited.source.reference == "EVID_001:revision"
    assert edited.confidence is Confidence.EXPLICIT
    assert not edited.user_confirmed
