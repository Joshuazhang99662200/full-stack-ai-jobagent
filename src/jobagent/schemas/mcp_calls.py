"""Actual read-only MCP calls and explicitly host-observed delivery facts."""

from typing import Literal

from pydantic import AwareDatetime, Field, HttpUrl, JsonValue, field_validator, model_validator

from jobagent.schemas.candidate import CandidateId
from jobagent.schemas.common import ContractModel, Digest, NonEmptyString
from jobagent.schemas.job_intelligence import JobListing
from jobagent.schemas.sourcing import SourcingQuerySelection


class McpContract(ContractModel):
    @field_validator("*")
    @classmethod
    def nonblank_evidence(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            raise ValueError("MCP identities and evidence cannot be blank.")
        return value


class McpRoundRequest(McpContract):
    run_id: NonEmptyString
    sourcing_run_id: NonEmptyString
    candidate_id: CandidateId
    source: NonEmptyString
    rules_version: Digest
    code_revision: Digest | None = None
    previous_run_id: NonEmptyString | None = None

    @field_validator("source")
    @classmethod
    def canonical_source(cls, value: str) -> str:
        if value != value.strip().casefold():
            raise ValueError("MCP source identity must be canonical lowercase.")
        return value


class McpRound(McpRoundRequest):
    opened_at: AwareDatetime
    mcp_total: int = Field(ge=1)
    max_parallel: int = Field(ge=1)
    batch_size: int = Field(ge=1)
    liepin_call_limit: int | None = Field(default=None, ge=1)
    delivery_spacing_seconds: float | None = Field(default=None, ge=5)
    code_revision: Digest


class McpCallRequest(McpContract):
    call_id: NonEmptyString
    run_id: NonEmptyString
    batch_id: NonEmptyString
    operation: Literal["search", "view"]
    arguments: dict[str, JsonValue] = Field(default_factory=dict)
    search_term: NonEmptyString | None = None
    source_job_id: NonEmptyString | None = None
    target_url: HttpUrl | None = None

    @model_validator(mode="after")
    def exact_target(self) -> "McpCallRequest":
        if self.operation == "search":
            if self.search_term is None or self.source_job_id is not None or self.target_url:
                raise ValueError("A search needs exact search text and no detail target.")
        elif self.source_job_id is None or self.target_url is None or self.search_term is not None:
            raise ValueError("A view needs the exact source job identity and URL.")
        return self


class McpProviderResult(McpContract):
    status: Literal["success", "failed", "gate", "unknown", "already_applied", "blocked"]
    payload: JsonValue = None
    error_code: str | None = None
    reason: str | None = None
    failure_details: dict[str, JsonValue] = Field(default_factory=dict)
    listings: list[JobListing] | None = None
    loaded: bool = False
    next_cursor: str | None = None


class McpBudget(McpContract):
    run_id: NonEmptyString
    candidate_id: CandidateId
    source: NonEmptyString
    rules_version: Digest
    code_revision: Digest
    activated: bool
    closed: bool
    base_allowance: int = Field(ge=1)
    previous_run_id: str | None = None
    previous_delivery_debit: int = Field(ge=0)
    starting_remaining: int = Field(ge=0)
    actual_calls: int = Field(ge=0)
    search_view_calls: int = Field(ge=0)
    mcp_total: int = Field(ge=1)
    remaining: int = Field(ge=0)
    max_parallel: int = Field(ge=1)
    batch_size: int = Field(ge=1)
    halted: bool


class McpCallReceipt(McpContract):
    call_id: NonEmptyString
    run_id: NonEmptyString
    batch_id: NonEmptyString
    operation: Literal["search", "view"]
    admitted_at: AwareDatetime
    dispatched_at: AwareDatetime | None = None
    completed_at: AwareDatetime
    dispatched: bool
    status: Literal[
        "success",
        "failed",
        "gate",
        "unknown",
        "already_applied",
        "blocked",
        "not_called",
    ]
    result: McpProviderResult
    budget: McpBudget
    selection: SourcingQuerySelection | None = None
    grants_delivery_permission: Literal[False] = False


class McpCallReconciliation(McpContract):
    call_id: NonEmptyString
    result: McpProviderResult
    source_reference: NonEmptyString
    observed_by: NonEmptyString
    observed_at: AwareDatetime
    positive_readback: bool = False
    provenance: Literal["host_observed"] = "host_observed"

    @model_validator(mode="after")
    def final_observed_outcome(self) -> "McpCallReconciliation":
        if self.result.status == "unknown":
            raise ValueError("Reconciliation requires an actual resolved outcome.")
        if self.result.status == "success" and not self.positive_readback:
            raise ValueError("Successful reconciliation requires positive readback evidence.")
        return self


class McpDeliveryIntent(McpContract):
    action_id: NonEmptyString
    run_id: NonEmptyString
    source_job_id: NonEmptyString
    item_approval_reference: NonEmptyString


class McpDeliveryHandoff(McpContract):
    intent: McpDeliveryIntent
    prepared_at: AwareDatetime
    executable: Literal[False] = False
    grants_delivery_permission: Literal[False] = False


class McpDeliveryObservation(McpContract):
    action_id: NonEmptyString
    run_id: NonEmptyString
    source_job_id: NonEmptyString
    status: Literal["sent", "failed", "unknown", "already_applied", "blocked", "gate"]
    occurred_at: AwareDatetime
    observed_at: AwareDatetime
    observed_by: NonEmptyString
    source_reference: NonEmptyString
    external_reference: NonEmptyString | None = None
    readback_reference: NonEmptyString | None = None
    evidence_text: NonEmptyString = Field(repr=False)
    positive_readback: bool = False
    provenance: Literal["host_observed"] = "host_observed"
    executed_by_gateway: Literal[False] = False

    @model_validator(mode="after")
    def actual_positive_readback(self) -> "McpDeliveryObservation":
        if self.occurred_at > self.observed_at:
            raise ValueError("Readback cannot predate the observed external action.")
        if self.status == "sent" and (
            not self.positive_readback
            or self.external_reference is None
            or self.readback_reference is None
        ):
            raise ValueError("A sent fact requires an external identity and positive readback.")
        return self
