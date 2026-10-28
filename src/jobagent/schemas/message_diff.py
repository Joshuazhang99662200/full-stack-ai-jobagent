"""Private draft/final comparisons and explicit owner rule decisions."""

from typing import Literal

from pydantic import AwareDatetime, Field

from jobagent.schemas.candidate import CandidateId
from jobagent.schemas.common import ContractModel, Digest, NonEmptyString
from jobagent.schemas.jobs import JobId

DiffCategory = Literal[
    "fact_correction",
    "job_routing",
    "business_specificity",
    "technical_accuracy",
    "style",
    "motivation",
]


class DiffSpan(ContractModel):
    initial_start: int = Field(ge=0)
    initial_end: int = Field(ge=0)
    final_start: int = Field(ge=0)
    final_end: int = Field(ge=0)


class DiffLabel(DiffSpan):
    category: DiffCategory


class MessageDiffInput(ContractModel):
    event_id: NonEmptyString
    candidate_id: CandidateId
    job_id: JobId
    draft_reference: NonEmptyString
    occurred_at: AwareDatetime
    source_reference: NonEmptyString
    initial_text: NonEmptyString = Field(repr=False)
    final_text: NonEmptyString = Field(repr=False)
    initial_hash: Digest
    final_hash: Digest
    classifier_reference: NonEmptyString | None = None
    labels: list[DiffLabel] = Field(default_factory=list, max_length=100)
    human_picked: bool | None = None
    job_preference: Literal["like", "dislike", "neutral"] | None = None
    message_feedback: Literal["accepted", "modified", "rejected"] | None = None


class MessageDiffResult(ContractModel):
    event_id: str
    changed: bool
    categories: list[DiffCategory]
    hunks: list[DiffSpan]
    classification_status: Literal[
        "unchanged", "needs_classification", "proposed", "punctuation_only"
    ]
    initial_hash: Digest
    final_hash: Digest
    send_proof_verified: Literal[False] = False


class MessageRuleProposal(ContractModel):
    proposal_id: NonEmptyString
    candidate_id: CandidateId
    category: DiffCategory
    rule_text: NonEmptyString = Field(repr=False)
    report_digest: Digest


class MessageRuleConfirmation(ContractModel):
    confirmation_id: NonEmptyString
    proposal_id: NonEmptyString
    candidate_id: CandidateId
    rule_hash: Digest
    accepted: bool
    owner_text: NonEmptyString = Field(repr=False)
    owner_reference: NonEmptyString
