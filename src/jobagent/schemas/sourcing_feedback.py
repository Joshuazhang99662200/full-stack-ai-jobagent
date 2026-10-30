"""Owner decisions and their bounded effects on future sourcing priorities."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, model_validator

from jobagent.schemas.candidate import CandidateId
from jobagent.schemas.common import ContractModel, Digest, NonEmptyString
from jobagent.schemas.jobs import JobId

FeedbackReason = Literal[
    "job_dislike", "salary", "location", "direction", "level", "copy", "facts", "later", "other"
]
SOURCING_REASONS = frozenset({"job_dislike", "salary", "location", "direction", "level"})


class SourcingFeedback(ContractModel):
    event_id: NonEmptyString
    job_id: JobId
    source: NonEmptyString
    search_term: str | None = None
    query_strategy_version: NonEmptyString
    action: Literal["approve", "revise", "decline"]
    reason_category: FeedbackReason = "other"
    free_text: str = ""
    content_digest: Digest
    actor_id: NonEmptyString
    occurred_at: datetime
    idempotency_key: NonEmptyString
    candidate_id: CandidateId | None = None
    original_text: str | None = None
    revised_text: str | None = None
    jd_text: str | None = None
    job_title: str | None = None
    company: str | None = None

    @model_validator(mode="after")
    def require_revision_provenance(self) -> "SourcingFeedback":
        if self.action == "revise" and (
            self.candidate_id is None or any(not value or not value.strip() for value in (
                self.original_text, self.revised_text, self.jd_text, self.job_title, self.company,
            ))
        ):
            raise ValueError("Revision feedback needs a candidate and exact draft/JD snapshots.")
        return self

    @property
    def affects_sourcing(self) -> bool:
        return self.action == "decline" and (
            self.candidate_id is not None or self.reason_category in SOURCING_REASONS
        )


class FeedbackSearchStrategy(ContractModel):
    version: NonEmptyString
    previous_version: NonEmptyString
    source: NonEmptyString
    candidate_id: CandidateId | None = None
    actor_id: NonEmptyString | None = None
    observed_feedback_ids: list[str] = Field(default_factory=list)
    ordered_queries: list[NonEmptyString]
    query_penalties: dict[str, int] = Field(default_factory=dict)
    deprioritized_job_ids: list[JobId] = Field(default_factory=list)
    generator_feedback_ids: list[str] = Field(default_factory=list)
    collection_feedback_ids: list[str] = Field(default_factory=list)
    applied_feedback_ids: list[str] = Field(default_factory=list)
    explanations: list[str] = Field(default_factory=list)
    # Priorities only: no feedback can grant delivery or alter hard constraints.
    changes_hard_constraints: Literal[False] = False


class PagedCardState(ContractModel):
    message_id: NonEmptyString
    batch_id: NonEmptyString
    ask_id: NonEmptyString
    page: Annotated[int, Field(ge=0)] = 0
    revision: Annotated[int, Field(ge=0)] = 0
    drafts: dict[str, str] = Field(default_factory=dict)
    feedback_drafts: dict[str, dict[str, str]] = Field(default_factory=dict)
    decisions: dict[str, Literal["approved", "revision_requested", "declined"]] = Field(
        default_factory=dict
    )
    approved_batches: dict[str, str] = Field(default_factory=dict)
    query_strategy_version: NonEmptyString = "unversioned"
    candidate_id: str | None = None
    expires_at: datetime
    closed: bool = False
    demo_mode: bool = False


class JobDecisionDetail(ContractModel):
    location: str | None = None
    salary_text: str | None = None
    points: list[str] = Field(default_factory=list)
    match_score: Annotated[float, Field(ge=0, le=1)] | None = None
    match_tier: str | None = None
    match_version: str | None = None
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
