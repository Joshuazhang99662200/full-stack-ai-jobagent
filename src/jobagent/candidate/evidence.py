"""Explicit candidate evidence lifecycle policies."""

from jobagent.candidate.ports import CandidateRepository
from jobagent.errors import MissingEvidenceError, PolicyRejectionError
from jobagent.schemas.candidate import Confidence, EvidenceItem
from jobagent.schemas.common import SourceReference, SourceType


class CandidateEvidenceService:
    """Keep draft creation, user editing, and confirmation as distinct operations."""

    def __init__(self, repository: CandidateRepository) -> None:
        self.repository = repository

    def get(self, candidate_id: str, evidence_id: str) -> EvidenceItem | None:
        return self.repository.get_evidence(candidate_id, evidence_id)

    def add_draft(self, candidate_id: str, evidence: EvidenceItem) -> EvidenceItem:
        if evidence.user_confirmed:
            raise PolicyRejectionError(
                "Draft evidence cannot arrive already confirmed.",
                details={"candidate_id": candidate_id, "evidence_id": evidence.id},
            )
        self.repository.upsert_evidence(candidate_id, evidence)
        return evidence

    def confirm(self, candidate_id: str, evidence_id: str) -> EvidenceItem:
        evidence = self._required(candidate_id, evidence_id)
        if evidence.confidence is Confidence.WEAK:
            raise PolicyRejectionError(
                "Weak evidence cannot be confirmed.",
                details={"candidate_id": candidate_id, "evidence_id": evidence_id},
            )
        confirmed = EvidenceItem.model_validate(
            {**evidence.model_dump(mode="python"), "user_confirmed": True}
        )
        self.repository.upsert_evidence(candidate_id, confirmed)
        return confirmed

    def replace_with_user_edit(
        self,
        candidate_id: str,
        evidence_id: str,
        statement: str,
    ) -> EvidenceItem:
        evidence = self._required(candidate_id, evidence_id)
        edited = EvidenceItem.model_validate(
            {
                **evidence.model_dump(mode="python"),
                "statement": statement,
                "source": SourceReference(
                    type=SourceType.USER_EDIT,
                    reference=f"{evidence_id}:revision",
                ),
                "confidence": Confidence.EXPLICIT,
                "user_confirmed": False,
            }
        )
        self.repository.upsert_evidence(candidate_id, edited)
        return edited

    def _required(self, candidate_id: str, evidence_id: str) -> EvidenceItem:
        evidence = self.repository.get_evidence(candidate_id, evidence_id)
        if evidence is None:
            raise MissingEvidenceError(
                "Candidate evidence was not found.",
                details={"candidate_id": candidate_id, "evidence_id": evidence_id},
            )
        return evidence
