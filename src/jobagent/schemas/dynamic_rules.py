"""Versioned owner parameter changes; no rule snapshot grants external permissions."""

from typing import Literal

from pydantic import AwareDatetime, Field, JsonValue

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


class RuleChangeRequest(ContractModel):
    candidate_id: CandidateId
    name: NonEmptyString
    value: JsonValue
    provenance: RuleProvenance
    expected_version: Digest | None = None


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
