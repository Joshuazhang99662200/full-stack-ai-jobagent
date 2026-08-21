"""Candidate resume-ingestion application service."""

from pathlib import Path

from jobagent.candidate.ports import CandidateDraftExtractor, CandidateRepository, ResumeParser
from jobagent.errors import ContractValidationError
from jobagent.schemas.candidate import CandidateDraft


class CandidateOnboardingService:
    """Coordinate deterministic parsing, structured extraction, and one repository commit."""

    def __init__(
        self,
        parser: ResumeParser,
        extractor: CandidateDraftExtractor,
        repository: CandidateRepository,
    ) -> None:
        self.parser = parser
        self.extractor = extractor
        self.repository = repository

    def ingest_resume(self, source_path: Path, candidate_id: str) -> CandidateDraft:
        parsed = self.parser.parse(source_path, candidate_id)
        if parsed.candidate_id != candidate_id:
            raise ContractValidationError(
                "Parsed resume candidate mismatch.",
                details={"candidate_id": candidate_id, "resume_id": parsed.id},
            )

        draft = self.extractor.extract(parsed)
        if draft.candidate_id != candidate_id or draft.profile.id != candidate_id:
            raise ContractValidationError(
                "Candidate draft candidate mismatch.",
                details={"candidate_id": candidate_id, "resume_id": parsed.id},
            )

        self.repository.save_onboarding(parsed, draft)
        return draft
