"""Compatibility diagnostics for existing production pipeline policy consumers."""

from typing import Literal

from pydantic import Field, JsonValue

from jobagent.schemas.candidate import CandidateId
from jobagent.schemas.common import ContractModel, Digest, NonEmptyString

PipelinePolicyConsumer = Literal["state", "diagnosis"]


class PipelinePolicyConflict(ContractModel):
    variable: NonEmptyString
    reason: Literal["missing_value", "unsupported_value", "future_version", "scope_mismatch"]
    configured: JsonValue = None
    supported: JsonValue = None


class PipelinePolicyCheck(ContractModel):
    candidate_id: CandidateId
    consumer: PipelinePolicyConsumer
    rules_version: Digest | None = None
    status: Literal["legacy", "compatible", "not_integrated"]
    can_write: bool
    referenced_variables: list[str] = Field(default_factory=list)
    conflicts: list[PipelinePolicyConflict] = Field(default_factory=list)
    grants_execution_permission: Literal[False] = False
