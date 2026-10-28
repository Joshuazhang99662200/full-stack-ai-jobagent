"""Read-only sourcing budgets: a permit never grants contact or delivery."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, HttpUrl, StringConstraints, model_validator

from jobagent.schemas.candidate import CandidateId
from jobagent.schemas.common import ContractModel

SourcingId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


BudgetProfile = Literal["conservative", "muse-expanded-v1"]


class QueryBudget(ContractModel):
    budget_profile: BudgetProfile = "conservative"
    query_limit: int = Field(default=3, ge=1, le=12)

    @model_validator(mode="after")
    def check_query_policy(self) -> "QueryBudget":
        if self.budget_profile == "conservative" and self.query_limit > 6:
            raise ValueError("Conservative query limit cannot exceed six.")
        if self.budget_profile == "muse-expanded-v1" and "query_limit" not in self.model_fields_set:
            raise ValueError("Expanded policy requires an explicit query limit.")
        return self


class SourcingRunRequest(QueryBudget):
    run_id: SourcingId
    candidate_id: CandidateId
    source: SourcingId
    detail_limit: Annotated[int, Field(ge=1, le=60)] = 20

    budget_profile: BudgetProfile = "conservative"
    daily_detail_cap: int | None = Field(default=None, ge=1, le=240)

    @model_validator(mode="after")
    def check_detail_policy(self) -> "SourcingRunRequest":
        if self.budget_profile == "conservative":
            if self.detail_limit > 50 or (self.daily_detail_cap or 0) > 50:
                raise ValueError("Expanded detail limits require the explicit expanded policy.")
        elif (
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
