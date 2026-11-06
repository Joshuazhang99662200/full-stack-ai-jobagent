"""Owner decisions and their bounded effects on future sourcing priorities."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from jobagent.schemas.candidate import CandidateId
from jobagent.schemas.common import ContractModel, Digest, NonEmptyString
from jobagent.schemas.jobs import JobId
from jobagent.schemas.outreach import ItemNumber, OutreachAskId, OutreachBatchId

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
    """Per-item decisions over one asked list, whichever host front end collected them."""

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
    # Card channels expired with the card; panel states rely on digest checks instead.
    expires_at: datetime | None = None
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


class OutreachFeedbackItem(ContractModel):
    """The person's decision on one numbered item of a list that was put to them."""

    number: ItemNumber
    action: Literal["approve", "revise", "decline"]
    reason_category: FeedbackReason = "other"
    free_text: Annotated[str, Field(max_length=1000)] = ""
    revised_text: Annotated[str, Field(min_length=1, max_length=1000)] | None = None

    @model_validator(mode="after")
    def revision_carries_words(self) -> "OutreachFeedbackItem":
        if (self.action == "revise") != (self.revised_text is not None):
            raise ValueError("Only a revision carries revised words, and it must carry them.")
        return self


class OutreachFeedbackRequest(ContractModel):
    """Host-neutral record of owner feedback; it approves and sends nothing."""

    batch_id: OutreachBatchId
    ask_id: OutreachAskId
    candidate_id: CandidateId
    actor_id: NonEmptyString
    # The person's own words, verbatim, as they answered the list.
    attestation: NonEmptyString
    occurred_at: AwareDatetime
    query_strategy_version: NonEmptyString = "unversioned"
    items: list[OutreachFeedbackItem] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def one_decision_per_item(self) -> "OutreachFeedbackRequest":
        numbers = [item.number for item in self.items]
        if len(numbers) != len(set(numbers)):
            raise ValueError("Each listed item takes at most one decision.")
        return self


class OutreachFeedbackLink(ContractModel):
    """Binds one feedback event to the exact asked item and words it judged."""

    event_id: NonEmptyString
    batch_id: OutreachBatchId
    ask_id: OutreachAskId
    item_number: ItemNumber
    words: NonEmptyString
    attestation: NonEmptyString


class OutreachFeedbackOutcome(ContractModel):
    number: ItemNumber
    event_id: NonEmptyString
    status: Literal["stored", "duplicate"]


class OutreachFeedbackReceipt(ContractModel):
    batch_id: OutreachBatchId
    ask_id: OutreachAskId
    items: list[OutreachFeedbackOutcome]
    # Feedback shapes future priorities and drafts only.
    grants_approval: Literal[False] = False
    grants_send: Literal[False] = False
