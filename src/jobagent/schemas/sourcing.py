"""Read-only sourcing budgets: a permit never grants contact or delivery."""
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, HttpUrl, StringConstraints, model_validator

from jobagent.schemas.candidate import CandidateId
from jobagent.schemas.common import ContractModel

SourcingId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class SourcingRunRequest(ContractModel):
    run_id: SourcingId
    candidate_id: CandidateId
    source: SourcingId
    query_limit: Annotated[int, Field(ge=1, le=6)] = 3
    detail_limit: Annotated[int, Field(ge=1, le=50)] = 20


class SourcingRun(SourcingRunRequest):
    opened_at: AwareDatetime
    daily_detail_limit: Annotated[int, Field(ge=1, le=50)]


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
    daily_cap: Annotated[int, Field(ge=1, le=50)]
    read_today: Annotated[int, Field(ge=0)]
    remaining: Annotated[int, Field(ge=0)]
    legacy_unmetered: Annotated[int, Field(ge=0)] = 0
    query_attempts_today: Annotated[int, Field(ge=0)] = 0
    listing_observations_today: Annotated[int, Field(ge=0)] = 0
    halted: bool = False


SourcingRefusal = Literal[
    "already_reserved", "expired_run", "site_halted",
    "round_query_limit", "round_detail_limit", "daily_detail_limit",
]


class SourcingPermit(ContractModel):
    allowed: bool
    reason: SourcingRefusal | Literal["allowed"]
    query_remaining: Annotated[int, Field(ge=0)]
    detail_remaining: Annotated[int, Field(ge=0)]
    budget: SourcingBudget
    attempt: SourcingAttempt | None = None
    grants_delivery_permission: Literal[False] = False
