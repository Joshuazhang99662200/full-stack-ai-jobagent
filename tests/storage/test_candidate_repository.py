from datetime import UTC, datetime
from pathlib import Path

import pytest

from jobagent.errors import StorageError
from jobagent.schemas.candidate import (
    CandidateDraft,
    CandidateProfile,
    Confidence,
    EvidenceItem,
    EvidenceType,
    InterviewEvent,
    InterviewEventType,
    ParsedResume,
    ResumePage,
)
from jobagent.schemas.common import SourceReference, SourceType
from jobagent.storage.candidate_repository import SqliteCandidateRepository
from jobagent.storage.database import Database


def repository_at(path: Path) -> SqliteCandidateRepository:
    database = Database(path)
    database.migrate()
    return SqliteCandidateRepository(database)


def evidence(evidence_id: str, statement: str) -> EvidenceItem:
    return EvidenceItem(
        id=evidence_id,
        type=EvidenceType.EXPERIENCE,
        statement=statement,
        source=SourceReference(type=SourceType.RESUME, reference="RESUME_001:page:1"),
        confidence=Confidence.EXPLICIT,
    )


def test_profile_round_trip_and_missing_record(tmp_path: Path) -> None:
    repository = repository_at(tmp_path / "candidate.sqlite3")
    profile = CandidateProfile(id="CAND_001", full_name="Ada Lovelace")

    assert repository.get_profile("CAND_001") is None
    repository.save_profile(profile)

    assert repository.get_profile("CAND_001") == profile


def test_evidence_upsert_and_candidate_isolation(tmp_path: Path) -> None:
    repository = repository_at(tmp_path / "candidate.sqlite3")
    repository.save_profile(CandidateProfile(id="CAND_001"))
    repository.save_profile(CandidateProfile(id="CAND_002"))
    first = evidence("EVID_001", "Built internal tooling.")
    updated = evidence("EVID_001", "Built internal tooling used by five teams.")
    second_candidate = evidence("EVID_002", "Led a migration.")

    repository.upsert_evidence("CAND_001", first)
    repository.upsert_evidence("CAND_001", updated)
    repository.upsert_evidence("CAND_002", second_candidate)

    assert repository.get_evidence("CAND_001", "EVID_001") == updated
    assert repository.get_evidence("CAND_001", "EVID_002") is None
    assert repository.list_evidence("CAND_001") == [updated]

    with pytest.raises(StorageError, match="belongs to another candidate"):
        repository.upsert_evidence("CAND_002", updated)


def test_resume_ingestion_round_trip(tmp_path: Path) -> None:
    repository = repository_at(tmp_path / "candidate.sqlite3")
    repository.save_profile(CandidateProfile(id="CAND_001"))
    resume = ParsedResume(
        id="RESUME_001",
        candidate_id="CAND_001",
        source_name="resume.pdf",
        content_digest="sha256:abc123",
        pages=[ResumePage(page_number=1, text="Experience")],
    )

    assert repository.get_resume("RESUME_001") is None
    repository.save_resume(resume)

    assert repository.get_resume("RESUME_001") == resume


def test_resume_reingest_is_idempotent_and_candidate_isolated(tmp_path: Path) -> None:
    repository = repository_at(tmp_path / "candidate.sqlite3")
    repository.save_profile(CandidateProfile(id="CAND_001"))
    repository.save_profile(CandidateProfile(id="CAND_002"))
    resume = ParsedResume(
        id="RESUME_001",
        candidate_id="CAND_001",
        source_name="resume.pdf",
        content_digest="sha256:abc123",
        pages=[ResumePage(page_number=1, text="Experience")],
    )
    reparsed = resume.model_copy(update={"pages": [ResumePage(page_number=1, text="Updated")]})

    repository.save_resume(resume)
    repository.save_resume(reparsed)

    assert repository.get_resume("RESUME_001") == reparsed

    with pytest.raises(StorageError, match="belongs to another candidate"):
        repository.save_resume(resume.model_copy(update={"candidate_id": "CAND_002"}))


def test_interview_events_are_append_only(tmp_path: Path) -> None:
    repository = repository_at(tmp_path / "candidate.sqlite3")
    repository.save_profile(CandidateProfile(id="CAND_001"))
    event = InterviewEvent(
        id="EVENT_001",
        candidate_id="CAND_001",
        event_type=InterviewEventType.QUESTION,
        question_id="QUESTION_001",
        payload={"text": "What was your scope?"},
        created_at=datetime(2026, 8, 21, tzinfo=UTC),
    )

    repository.append_interview_event(event)
    with pytest.raises(StorageError, match="append interview event"):
        repository.append_interview_event(event)

    assert repository.list_interview_events("CAND_001") == [event]


def test_onboarding_write_rolls_back_as_one_transaction(tmp_path: Path) -> None:
    repository = repository_at(tmp_path / "candidate.sqlite3")
    original = CandidateProfile(id="CAND_001", full_name="Original Name")
    repository.save_profile(original)
    # The resume references a candidate that was never persisted, so the ingestion
    # insert violates its foreign key part-way through the onboarding transaction.
    parsed = ParsedResume(
        id="RESUME_001",
        candidate_id="CAND_MISSING",
        source_name="resume.pdf",
        content_digest="sha256:abc123",
        pages=[ResumePage(page_number=1, text="Experience")],
    )
    candidate_evidence = evidence("EVID_001", "Built internal tooling.")
    draft = CandidateDraft(
        candidate_id="CAND_001",
        profile=CandidateProfile(id="CAND_001", full_name="Updated Name"),
        evidence=[candidate_evidence],
    )

    with pytest.raises(StorageError, match="save candidate onboarding"):
        repository.save_onboarding(parsed, draft)

    assert repository.get_profile("CAND_001") == original
    assert repository.get_evidence("CAND_001", "EVID_001") is None
