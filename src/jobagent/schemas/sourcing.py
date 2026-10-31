"""Read-only sourcing budgets: a permit never grants contact or delivery."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, HttpUrl, StringConstraints, model_validator

from jobagent.schemas.candidate import CandidateId
from jobagent.schemas.common import ContractModel, Digest, NonEmptyString
from jobagent.schemas.dynamic_rules import RuleConfirmation, RuleProposal
from jobagent.schemas.job_intelligence import JobListing

SourcingId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


BudgetProfile = Literal["conservative", "muse-expanded-v1"]


class QueryBudget(ContractModel):
    budget_profile: BudgetProfile = "conservative"
    query_limit: int = Field(default=3, ge=1, le=12)

    @model_validator(mode="after")
    def check_query_policy(self) -> "QueryBudget":
        if self.budget_profile == "conservative" and self.query_limit > 6:
            raise ValueError("Conservative query limit cannot exceed six.")
        if (self.budget_profile == "muse-expanded-v1"
                and "query_limit" not in self.model_fields_set
                and getattr(self, "rules_version", None) is None):
            raise ValueError("Expanded policy requires an explicit query limit.")
        return self


class ConfirmedRoundOverride(ContractModel):
    proposal: RuleProposal
    confirmation: RuleConfirmation


class SourcingRunRequest(QueryBudget):
    run_id: SourcingId
    candidate_id: CandidateId
    source: SourcingId
    detail_limit: Annotated[int, Field(ge=1, le=60)] = 20

    budget_profile: BudgetProfile = "conservative"
    daily_detail_cap: int | None = Field(default=None, ge=1, le=240)
    top_per_query: int | None = Field(default=None, ge=1)
    rules_version: Digest | None = None
    base_rules_version: Digest | None = None
    code_revision: Digest | None = None
    round_overrides: list[ConfirmedRoundOverride] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_detail_policy(self) -> "SourcingRunRequest":
        if self.budget_profile == "conservative":
            if self.detail_limit > 50 or (self.daily_detail_cap or 0) > 50:
                raise ValueError("Expanded detail limits require the explicit expanded policy.")
        elif self.rules_version is None and (
            self.daily_detail_cap is None
            or not {"detail_limit", "daily_detail_cap"} <= self.model_fields_set
        ):
            raise ValueError("Expanded rounds require explicit query, detail and daily limits.")
        return self


class SourcingRun(SourcingRunRequest):
    opened_at: AwareDatetime
    daily_detail_limit: Annotated[int, Field(ge=1, le=240)]


class SourcingAttemptRequest(ContractModel):
    attempt_id: SourcingId
    run_id: SourcingId
    kind: Literal["query", "detail"]
    search_term: SourcingId | None = None
    source_job_id: SourcingId | None = None
    url: HttpUrl | None = None

    @model_validator(mode="after")
    def check_target(self) -> "SourcingAttemptRequest":
        if self.kind == "query":
            if self.search_term is None or self.source_job_id is not None or self.url is not None:
                raise ValueError("Queries need exact search text and no detail target.")
        elif self.source_job_id is None or self.url is None:
            raise ValueError("Detail attempts require the source job ID and detail URL.")
        return self


class SourcingAttempt(SourcingAttemptRequest):
    source: SourcingId
    occurred_at: AwareDatetime


class SourcingResultRequest(ContractModel):
    attempt_id: SourcingId
    outcome: Literal["complete", "partial", "failed", "gate", "cancelled"]
    listing_count: Annotated[int, Field(ge=0)] | None = None


class SourcingResult(SourcingResultRequest):
    source: SourcingId
    completed_at: AwareDatetime


class SourcingBudget(ContractModel):
    source: SourcingId
    daily_cap: Annotated[int, Field(ge=1, le=240)]
    read_today: Annotated[int, Field(ge=0)]
    remaining: Annotated[int, Field(ge=0)]
    legacy_unmetered: Annotated[int, Field(ge=0)] = 0
    query_attempts_today: Annotated[int, Field(ge=0)] = 0
    listing_observations_today: Annotated[int, Field(ge=0)] = 0
    halted: bool = False


SourcingRefusal = Literal[
    "already_reserved",
    "expired_run",
    "site_halted",
    "round_query_limit",
    "round_detail_limit",
    "daily_detail_limit",
]


class SourcingPermit(ContractModel):
    allowed: bool
    reason: SourcingRefusal | Literal["allowed"]
    query_remaining: Annotated[int, Field(ge=0)]
    detail_remaining: Annotated[int, Field(ge=0)]
    budget: SourcingBudget
    attempt: SourcingAttempt | None = None
    grants_delivery_permission: Literal[False] = False


class ReadReservation(ContractModel):
    attempt_id: NonEmptyString
    source: NonEmptyString
    target_url: HttpUrl
    profile: NonEmptyString
    expected_daily_cap: int = Field(ge=1, le=240)
    run_id: SourcingId | None = None
    candidate_id: CandidateId | None = None


class ReadOutcome(ContractModel):
    attempt_id: NonEmptyString
    status: Literal[
        "read", "failed", "login_required", "loading", "verification", "risk_control", "unknown",
    ]


class ReadReceipt(ContractModel):
    attempt_id: NonEmptyString
    source: NonEmptyString
    request_digest: Digest
    reserved_at: AwareDatetime
    daily_cap: int
    profile: NonEmptyString
    allowed: bool
    run_id: SourcingId | None = None
    rules_version: Digest | None = None


class QuerySelection(ContractModel):
    requested: int = Field(ge=1)
    observed_count: int = Field(ge=0)
    taken_count: int = Field(ge=0)
    shortfall: int = Field(ge=0)
    items: list[JobListing]
    duplicate_ids: list[str]


class SourcingQueryCapture(ContractModel):
    attempt_id: SourcingId
    items: list[JobListing]
    loaded: bool = False
    access_state: Literal["public", "authenticated", "unknown", "loading", "blocked"] = "unknown"
    next_cursor: str | None = None


class SourcingQuerySelection(QuerySelection):
    attempt_id: SourcingId
    run_id: SourcingId
    source: NonEmptyString
    rules_version: Digest
    next_cursor: str | None = None
    traversal_complete: Literal[False] = False


class SourcingDisposition(ContractModel):
    item_id: NonEmptyString
    status: Literal[
        "draft_ready", "needs_jd", "rejected", "duplicate", "closed", "unsupported", "deferred",
    ]
    reason: NonEmptyString


class SourcingCompletion(ContractModel):
    input_ids: list[NonEmptyString]
    dispositions: list[SourcingDisposition]
    stop_reason: Literal["complete", "budget", "intervention", "interrupted"]
    last_cursor: str | None = None
    access_state: Literal[
        "public", "authenticated", "login_required", "loading", "verification",
        "risk_control", "unknown",
    ] = "unknown"
    loaded: bool = False

    @model_validator(mode="after")
    def account_for_every_input(self) -> "SourcingCompletion":
        output_ids = [row.item_id for row in self.dispositions]
        if (len(set(self.input_ids)) != len(self.input_ids)
                or len(set(output_ids)) != len(output_ids)
                or set(self.input_ids) != set(output_ids)):
            raise ValueError("Every input needs exactly one disposition.")
        if self.stop_reason != "complete" and not self.last_cursor:
            raise ValueError("Partial collection requires a recovery cursor.")
        if self.stop_reason == "complete" and (
            self.access_state not in {"public", "authenticated"} or not self.loaded
        ):
            raise ValueError("Complete collection requires an accessible loaded view.")
        return self
