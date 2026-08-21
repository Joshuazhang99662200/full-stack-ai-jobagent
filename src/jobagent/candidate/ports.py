"""Ports owned by the Candidate Core."""

from pathlib import Path
from typing import Protocol, runtime_checkable

from jobagent.schemas.candidate import (
    CandidateDraft,
    CandidateProfile,
    EvidenceItem,
    InterviewEvent,
    ParsedResume,
)


@runtime_checkable
class ResumeParser(Protocol):
    def parse(self, path: Path, candidate_id: str) -> ParsedResume: ...


@runtime_checkable
class CandidateDraftExtractor(Protocol):
    def extract(self, resume: ParsedResume) -> CandidateDraft: ...


@runtime_checkable
class CandidateRepository(Protocol):
    def save_profile(self, profile: CandidateProfile) -> None: ...

    def get_profile(self, candidate_id: str) -> CandidateProfile | None: ...

    def upsert_evidence(self, candidate_id: str, evidence: EvidenceItem) -> None: ...

    def get_evidence(self, candidate_id: str, evidence_id: str) -> EvidenceItem | None: ...

    def list_evidence(self, candidate_id: str) -> list[EvidenceItem]: ...

    def save_resume(self, resume: ParsedResume) -> None: ...

    def get_resume(self, resume_id: str) -> ParsedResume | None: ...

    def append_interview_event(self, event: InterviewEvent) -> None: ...

    def list_interview_events(self, candidate_id: str) -> list[InterviewEvent]: ...

    def save_onboarding(self, resume: ParsedResume, draft: CandidateDraft) -> None: ...

