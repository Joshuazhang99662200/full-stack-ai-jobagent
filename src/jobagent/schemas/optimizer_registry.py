"""Strict contracts for the Optimizer functional capability index."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StringConstraints, field_validator, model_validator

from jobagent.schemas.common import ContractModel

RegistryNonEmptyString = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]
CapabilityId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)+$",
    ),
]
SemanticVersion = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=(
            r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
            r"(?:-(?:0|[1-9]\d*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
            r"(?:\.(?:0|[1-9]\d*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*)?"
            r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
        ),
    ),
]
RegistryDigest = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^sha256:[0-9a-f]{64}$",
    ),
]
RegistryDescription = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=40, max_length=500),
]


class RegistryContractModel(ContractModel):
    """Immutable base for data included in a registry snapshot."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        frozen=True,
        str_strip_whitespace=True,
    )


class CapabilityKind(StrEnum):
    CAPABILITY = "capability"
    POLICY = "policy"
    PROMPT_PACK = "prompt-pack"
    LENS = "lens"


class CapabilityPermission(StrEnum):
    CANDIDATE_PROFILE = "candidate_profile"
    CANDIDATE_EVIDENCE = "candidate_evidence"
    RESUME_SOURCE = "resume_source"
    RESUME_ITEM = "resume_item"
    EVIDENCE_SUMMARY = "evidence_summary"
    TARGET_ROLE = "target_role"
    JOB_RECORD = "job_record"
    JOB_REQUIREMENTS = "job_requirements"
    REQUIREMENT_MATCHES = "requirement_matches"
    JOB_INTELLIGENCE = "job_intelligence"
    INTERVIEW_EVENT = "interview_event"
    DRAFT_EVIDENCE = "draft_evidence"
    CANONICAL_EVIDENCE = "canonical_evidence"
    OPTIMIZER_CONTRACTS = "optimizer_contracts"
    OPTIMIZATION_SESSION = "optimization_session"
    PERSPECTIVE_FINDING = "perspective_finding"
    STRATEGY_PROPOSAL = "strategy_proposal"
    REWRITE_PROPOSAL = "rewrite_proposal"
    VERIFICATION_FINDING = "verification_finding"
    USER_FEEDBACK = "user_feedback"
    POLICY_RESOURCE = "policy_resource"
    PROMPT_RESOURCE = "prompt_resource"
    CLAIM_LEDGER = "claim_ledger"
    RESUME_DIFF = "resume_diff"
    COMPATIBILITY_REPORT = "compatibility_report"


class TrustLevel(StrEnum):
    CORE = "core"
    PROJECT = "project"
    THIRD_PARTY = "third_party"


class RetryMode(StrEnum):
    NEVER = "never"
    TRANSIENT_ONCE = "transient_once"


class FailureFallback(StrEnum):
    RETURN_TYPED_FAILURE = "return_typed_failure"
    PAUSE_FOR_HUMAN = "pause_for_human"
    QUARANTINE_CAPABILITY = "quarantine_capability"


class CapabilityPermissions(RegistryContractModel):
    read: tuple[CapabilityPermission, ...]
    write: tuple[CapabilityPermission, ...]

    @field_validator("read", "write", mode="before")
    @classmethod
    def strip_permission_values(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(item.strip() if isinstance(item, str) else item for item in value)
        return value


class CapabilityFailurePolicy(RegistryContractModel):
    retry: RetryMode = RetryMode.NEVER
    fallback: FailureFallback = FailureFallback.RETURN_TYPED_FAILURE

    @field_validator("retry", "fallback", mode="before")
    @classmethod
    def strip_policy_values(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class CapabilityIndexEntry(RegistryContractModel):
    id: CapabilityId
    version: SemanticVersion
    kind: CapabilityKind
    description: RegistryDescription
    entrypoint: RegistryNonEmptyString
    input_schema: RegistryNonEmptyString | None
    output_schema: RegistryNonEmptyString | None
    intents: Annotated[tuple[RegistryNonEmptyString, ...], Field(min_length=1)]
    required_context: tuple[RegistryNonEmptyString, ...]
    permissions: CapabilityPermissions
    preconditions: tuple[RegistryNonEmptyString, ...]
    dependencies: tuple[CapabilityId, ...]
    produces: tuple[RegistryNonEmptyString, ...]
    verifiers: tuple[CapabilityId, ...]
    failure_policy: CapabilityFailurePolicy
    trust: TrustLevel

    @field_validator("kind", "trust", mode="before")
    @classmethod
    def strip_enum_values(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_kind_boundary(self) -> "CapabilityIndexEntry":
        executable = self.kind in {CapabilityKind.CAPABILITY, CapabilityKind.LENS}
        if executable and (self.input_schema is None or self.output_schema is None):
            raise ValueError("executable entries require input_schema and output_schema")
        if executable and not self.produces:
            raise ValueError("executable entries require at least one produces artifact")
        if not executable and (self.input_schema is not None or self.output_schema is not None):
            raise ValueError("non-executable entries forbid input_schema and output_schema")
        if not executable and self.permissions.write:
            raise ValueError("non-executable entries cannot write")
        return self


class CapabilityIndexDocument(RegistryContractModel):
    schema_version: Literal["1.0"]
    entries: Annotated[tuple[CapabilityIndexEntry, ...], Field(min_length=1)]


class CapabilityRegistrySnapshot(RegistryContractModel):
    entries: tuple[CapabilityIndexEntry, ...]
    digest: RegistryDigest

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "CapabilityRegistrySnapshot":
        ids = [entry.id for entry in self.entries]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate capability id")
        return self
