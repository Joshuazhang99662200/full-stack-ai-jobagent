"""Diagnosis-driven proposals; owner approval is separate from cumulative evidence."""

from pydantic import Field

from jobagent.schemas.candidate import CandidateId
from jobagent.schemas.common import ContractModel, Digest, NonEmptyString
from jobagent.schemas.message_diff import DiffCategory


class PipelineRuleProposalInput(ContractModel):
    proposal_id: NonEmptyString
    candidate_id: CandidateId
    diagnosis_id: NonEmptyString
    diagnosis_digest: Digest
    category: DiffCategory
    rule_text_after: NonEmptyString = Field(repr=False)
    previous_proposal_id: str | None = None
    rule_text_before: str | None = Field(default=None, repr=False)


class PipelineRuleConfirmationInput(ContractModel):
    confirmation_id: NonEmptyString
    proposal_id: NonEmptyString
    candidate_id: CandidateId
    rule_hash: Digest
    accepted: bool
    owner_text: NonEmptyString = Field(repr=False)
    owner_reference: NonEmptyString


class PipelineRuleReviewInput(ContractModel):
    review_id: NonEmptyString
    candidate_id: CandidateId
    rule_id: NonEmptyString
    diagnosis_id: NonEmptyString
    diagnosis_digest: Digest
