from pathlib import Path

import pytest

from jobagent.candidate.onboarding import CandidateOnboardingService
from jobagent.errors import ContractValidationError, InvalidProviderOutputError
from jobagent.schemas.candidate import (
    CandidateDraft,
    CandidateProfile,
    ParsedResume,
    ResumePage,
)


def resume(candidate_id: str = "CAND_001") -> ParsedResume:
    return ParsedResume(
        id="RESUME_001",
        candidate_id=candidate_id,
        source_name="resume.pdf",
        content_digest="sha256:abc123",
        pages=[ResumePage(page_number=1, text="Experience")],
    )


class FakeParser:
    def __init__(self, output: ParsedResume) -> None:
        self.output = output
        self.call: tuple[Path, str] | None = None

    def parse(self, path: Path, candidate_id: str) -> ParsedResume:
        self.call = (path, candidate_id)
        return self.output


class FakeExtractor:
    def __init__(
        self,
        output: CandidateDraft | None = None,
        error: Exception | None = None,
    ) -> None:
        self.output = output
        self.error = error
        self.input: ParsedResume | None = None

    def extract(self, parsed: ParsedResume) -> CandidateDraft:
        self.input = parsed
        if self.error is not None:
            raise self.error
        assert self.output is not None
        return self.output


class RecordingRepository:
    def __init__(self) -> None:
        self.saved: tuple[ParsedResume, CandidateDraft] | None = None

    def save_onboarding(self, parsed: ParsedResume, draft: CandidateDraft) -> None:
        self.saved = (parsed, draft)


def test_onboarding_parses_extracts_then_persists_once(tmp_path: Path) -> None:
    parsed = resume()
    draft = CandidateDraft(
        candidate_id="CAND_001",
        profile=CandidateProfile(id="CAND_001", full_name="Ada Lovelace"),
    )
    parser = FakeParser(parsed)
    extractor = FakeExtractor(draft)
    repository = RecordingRepository()
    source_path = tmp_path / "resume.pdf"

    result = CandidateOnboardingService(parser, extractor, repository).ingest_resume(
        source_path,
        "CAND_001",
    )

    assert result == draft
    assert parser.call == (source_path, "CAND_001")
    assert extractor.input == parsed
    assert repository.saved == (parsed, draft)


def test_extraction_failure_does_not_persist_partial_state(tmp_path: Path) -> None:
    repository = RecordingRepository()
    service = CandidateOnboardingService(
        FakeParser(resume()),
        FakeExtractor(error=InvalidProviderOutputError("bad draft")),
        repository,
    )

    with pytest.raises(InvalidProviderOutputError):
        service.ingest_resume(tmp_path / "resume.pdf", "CAND_001")

    assert repository.saved is None


def test_onboarding_rejects_cross_candidate_draft(tmp_path: Path) -> None:
    repository = RecordingRepository()
    mismatched = CandidateDraft(
        candidate_id="CAND_002",
        profile=CandidateProfile(id="CAND_002"),
    )
    service = CandidateOnboardingService(
        FakeParser(resume()),
        FakeExtractor(mismatched),
        repository,
    )

    with pytest.raises(ContractValidationError, match="candidate mismatch"):
        service.ingest_resume(tmp_path / "resume.pdf", "CAND_001")

    assert repository.saved is None
