"""Versioned owner parameter changes; no rule snapshot grants external permissions."""

from typing import Any, Literal

from pydantic import (
    AwareDatetime,
    Field,
    JsonValue,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
    model_validator,
)

from jobagent.schemas.candidate import CandidateId
from jobagent.schemas.common import ContractModel, Digest, NonEmptyString


class RuleProvenance(ContractModel):
    source_kind: Literal["user", "platform_reference", "host_proposal"]
    source_ref: NonEmptyString
    decided_at: AwareDatetime
    decided_by: NonEmptyString


class RuleDefinition(ContractModel):
    name: NonEmptyString
    category: Literal["user_parameter", "platform_reference", "snapshot", "invariant"]
    binding: Literal["runtime", "host", "proposal_only", "reference_only"]
    value_type: NonEmptyString
    description: NonEmptyString
    consumer: NonEmptyString = "reference only"
    default: JsonValue = None


class OwnerChangeRequest(ContractModel):
    """The owner's actual request to reopen configuration, never a host suggestion."""

    candidate_id: CandidateId
    names: list[NonEmptyString] = Field(min_length=1)
    owner_text: NonEmptyString
    source_reference: NonEmptyString
    actor_id: NonEmptyString
    requested_at: AwareDatetime
    scope: Literal["reusable", "round"] = "reusable"
    run_id: NonEmptyString | None = None

    @field_validator("owner_text", "source_reference", "actor_id")
    @classmethod
    def require_actual_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Owner change evidence cannot be blank.")
        return value

    @model_validator(mode="after")
    def check_scope(self) -> "OwnerChangeRequest":
        if len(set(self.names)) != len(self.names) or any(not name.strip() for name in self.names):
            raise ValueError("Requested names must be explicit and unique.")
        if (self.scope == "round") != (self.run_id is not None):
            raise ValueError("Round-only changes require exactly one run identity.")
        return self


class RuleChangeRequest(ContractModel):
    candidate_id: CandidateId
    name: NonEmptyString
    value: JsonValue
    provenance: RuleProvenance
    expected_version: Digest | None = None
    owner_request: OwnerChangeRequest | None = None

    @model_validator(mode="after")
    def check_owner_request(self) -> "RuleChangeRequest":
        owner = self.owner_request
        if owner is not None and (
            owner.candidate_id != self.candidate_id
            or self.name not in owner.names
            or owner.actor_id != self.provenance.decided_by
            or owner.requested_at > self.provenance.decided_at
        ):
            raise ValueError("Owner request does not match the candidate, variable, actor or time.")
        return self

    @model_serializer(mode="wrap")
    def preserve_existing_serialization(
        self, handler: SerializerFunctionWrapHandler,
    ) -> dict[str, Any]:
        body: dict[str, Any] = handler(self)
        if self.owner_request is None:
            body.pop("owner_request", None)
        return body


class RuleProposal(ContractModel):
    proposal_id: NonEmptyString
    candidate_id: CandidateId
    base_version: Digest | None = None
    request: RuleChangeRequest
    old_value: JsonValue = None
    question: NonEmptyString
    question_digest: Digest
    proposed_at: AwareDatetime


class RuleConfirmation(ContractModel):
    proposal_id: NonEmptyString
    question_digest: Digest
    answer: NonEmptyString
    actor_id: NonEmptyString
    confirmed_at: AwareDatetime
    confirmed_by: Literal["human"] = "human"


class DynamicRuleSet(ContractModel):
    candidate_id: CandidateId
    version: Digest
    parent_version: Digest | None = None
    effective_at: AwareDatetime
    values: dict[str, JsonValue] = Field(default_factory=dict)
    provenance: dict[str, RuleProvenance] = Field(default_factory=dict)


class RuleChangeNotice(ContractModel):
    candidate_id: CandidateId
    version: Digest
    name: NonEmptyString
    old_value: JsonValue = None
    new_value: JsonValue
    effective_at: AwareDatetime
    text: NonEmptyString
