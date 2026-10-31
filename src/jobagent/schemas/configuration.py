"""First-run configuration forms and ordinary-run reuse; never execution permission."""

from typing import Literal

from pydantic import AwareDatetime, Field, JsonValue

from jobagent.schemas.candidate import CandidateId
from jobagent.schemas.common import ContractModel, Digest, NonEmptyString
from jobagent.schemas.dynamic_rules import OwnerChangeRequest, RuleProvenance

BASE_CONFIGURATION_NAMES = (
    "QUERIES_PER_SITE_PER_ROUND",
    "TOP_PER_QUERY",
    "DETAIL_ATTEMPTS_PER_SITE_PER_ROUND",
    "DETAIL_CAP_PER_DAY",
)
ConfigurationMode = Literal["initial_setup", "ordinary_run", "owner_requested_change"]
ConfigurationFieldStatus = Literal["confirmed", "missing", "unsupported", "change_requested"]
ConfigurationPreparationStatus = Literal[
    "needs_user_decision", "blocked_by_missing_configuration", "blocked_by_conflict",
    "unsupported_consumer", "ready_to_initialize", "ready",
]


class ConfigurationPreparationRequest(ContractModel):
    candidate_id: CandidateId
    task_id: NonEmptyString
    task_type: NonEmptyString
    mode: ConfigurationMode = "ordinary_run"
    required_names: list[NonEmptyString] = Field(default_factory=list)
    owner_request: OwnerChangeRequest | None = None
    conflicts: list[NonEmptyString] = Field(default_factory=list)
    expected_version: Digest | None = None
    code_revision: NonEmptyString | None = None


class ConfigurationField(ContractModel):
    name: NonEmptyString
    label: NonEmptyString
    unit: NonEmptyString
    value: JsonValue = None
    status: ConfigurationFieldStatus
    consumer: NonEmptyString
    provenance: RuleProvenance | None = None


class ConfigurationPreparationResult(ContractModel):
    candidate_id: CandidateId
    task_id: NonEmptyString
    task_type: NonEmptyString
    mode: ConfigurationMode
    initialized: bool
    ready: bool = False
    can_initialize: bool = False
    ask_user: bool = False
    status: ConfigurationPreparationStatus
    questions: list[str] = Field(default_factory=list)
    fields: list[ConfigurationField] = Field(default_factory=list)
    rules_version: Digest | None = None
    code_revision: NonEmptyString | None = None
    reasons: list[str] = Field(default_factory=list)
    grants_execution_permission: Literal[False] = False


class ConfigurationInitialization(ContractModel):
    candidate_id: CandidateId
    rules_version: Digest
    initialized_at: AwareDatetime
