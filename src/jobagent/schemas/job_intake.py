"""Human job intake and durable host hand-off contracts; no sending authority."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, HttpUrl, StringConstraints, model_validator

from jobagent.schemas.candidate import CandidateId
from jobagent.schemas.common import ContractModel, Digest, NonEmptyString
from jobagent.schemas.job_intelligence import CandidateFilterContext, JobListing
from jobagent.schemas.jobs import JobId
from jobagent.schemas.outreach import OutreachDraft
from jobagent.schemas.search_learning import SearchLearningRequest, SearchSignal
from jobagent.schemas.sourcing import QueryBudget

IntakeKey = Annotated[str, StringConstraints(min_length=1, max_length=200)]


class IntakeRequest(ContractModel):
    request_id: IntakeKey
    candidate_id: CandidateId
    domain: NonEmptyString
    platform: NonEmptyString
    message_reference: IntakeKey
    entry_kind: Literal["url", "list_item", "conversation_card"]
    target_reference: IntakeKey
    list_version: IntakeKey | None = None
    job_url: HttpUrl | None = None
    source_job_id: IntakeKey | None = None
    intent: Literal["inspect", "draft"] = "inspect"
    job_preference: Literal["like", "dislike", "neutral"] | None = None
    owner_text: str = Field(default="", repr=False)
    occurred_at: AwareDatetime

    @model_validator(mode="after")
    def actual_context(self) -> "IntakeRequest":
        if self.entry_kind == "list_item" and not self.list_version:
            raise ValueError("List references need an immutable list version.")
        if self.entry_kind == "url" and self.job_url is None:
            raise ValueError("URL input needs the actual job URL.")
        if self.job_preference is not None and not self.owner_text.strip():
            raise ValueError("Job preferences need the actual owner's words.")
        return self


class IntakeSelection(ContractModel):
    candidate_id: CandidateId
    platform: NonEmptyString
    list_version: IntakeKey
    message_reference: IntakeKey
    observed_at: AwareDatetime
    targets: dict[IntakeKey, JobId | JobListing] = Field(min_length=1, max_length=200)


class IntakeCommand(ContractModel):
    event_id: IntakeKey
    intake_id: IntakeKey
    candidate_id: CandidateId
    expected_version: int = Field(ge=1)


class IntakeResolve(IntakeCommand):
    job_id: JobId | None = None
    listing: JobListing | None = None

    @model_validator(mode="after")
    def one_identity(self) -> "IntakeResolve":
        if (self.job_id is None) == (self.listing is None):
            raise ValueError("Choose a cached job or an actual listing.")
        return self


class IntakeSnapshot(IntakeCommand):
    snapshot_id: IntakeKey
    observation_id: IntakeKey | None = None
    attempt_id: IntakeKey | None = None


class IntakeDraft(IntakeCommand):
    draft: OutreachDraft
    author_reference: IntakeKey
    filter_context: CandidateFilterContext


class IntakeReview(IntakeCommand):
    draft_digest: Digest
    snapshot_id: IntakeKey
    reviewer_reference: IntakeKey
    review_reference: IntakeKey
    accepted: bool
    issues: list[str] = Field(default_factory=list)


class IntakeBatch(IntakeCommand):
    batch_id: IntakeKey


class IntakeInterest(IntakeCommand):
    job_preference: Literal["like", "dislike", "neutral"]
    owner_text: NonEmptyString = Field(repr=False)
    message_reference: IntakeKey


class IntakeControl(IntakeCommand):
    action: Literal["pause", "resume", "close"]
    reason: NonEmptyString
    owner_text: str | None = Field(default=None, repr=False)


class IntakeRecord(ContractModel):
    intake_id: IntakeKey
    candidate_id: CandidateId
    domain: str
    platform: str
    requests: list[IntakeRequest]
    version: int = Field(ge=1)
    created_at: AwareDatetime
    updated_at: AwareDatetime
    job_id: JobId | None = None
    listing: JobListing | None = None
    legacy_snapshot_id: Digest | None = None
    job_url: HttpUrl | None = None
    source_job_id: str | None = None
    snapshot_id: str | None = None
    snapshot_version: int | None = None
    jd_text_hash: Digest | None = None
    feature_set_id: Digest | None = None
    feature_policy_digest: Digest | None = None
    signal_id: str | None = None
    draft: OutreachDraft | None = Field(default=None, repr=False)
    draft_digest: Digest | None = None
    draft_author_reference: str | None = None
    filter_context: CandidateFilterContext | None = None
    review: IntakeReview | None = None
    batch_id: str | None = None
    plan_id: Digest | None = None
    lexicon_digest: Digest | None = None
    strategy_status: Literal["candidate", "selected", "deferred"] | None = None
    contacted: bool = False
    paused: bool = False
    closed: bool = False
    merged_into: str | None = None
    blocked_reason: str | None = None


class IntakeHistory(ContractModel):
    event_id: str
    kind: str
    input_digest: Digest
    command_digest: Digest | None = None
    state: IntakeRecord


class IntakeLegacyScope(ContractModel):
    external_snapshot_ids: list[str] = Field(default_factory=list, max_length=2000)
    historical_signals: list[SearchSignal] = Field(default_factory=list, max_length=2000)


class IntakeStrategyInput(QueryBudget):
    candidate_id: CandidateId
    domain: NonEmptyString
    source: NonEmptyString
    baseline_queries: list[NonEmptyString] = Field(min_length=1, max_length=10)
    snapshot_ids: list[str] = Field(default_factory=list, max_length=2000)
    historical_learning: SearchLearningRequest | None = None


class IntakeClaim(ContractModel):
    candidate_id: CandidateId
    domain: NonEmptyString
    run_id: IntakeKey


class IntakeSearchRecord(IntakeClaim):
    attempt_id: IntakeKey
    new_count: int = Field(ge=0)
