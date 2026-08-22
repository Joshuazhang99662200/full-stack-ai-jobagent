"""Strict contracts for the Optimizer functional capability index."""

from enum import StrEnum
from typing import Annotated

from pydantic import Field, model_validator

from jobagent.schemas.common import ContractModel, Digest, NonEmptyString

CapabilityId = Annotated[
    str,
    Field(pattern=r"^[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)+$"),
]
SemanticVersion = Annotated[
    str,
    Field(pattern=r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$"),
]


class CapabilityKind(StrEnum):
    CAPABILITY = "capability"
    POLICY = "policy"
    PROMPT_PACK = "prompt-pack"
    LENS = "lens"


class CapabilityRole(StrEnum):
    ANALYZE = "analyze"
    ENRICH = "enrich"
    STRATEGY = "strategy"
    REWRITE = "rewrite"
    VERIFY = "verify"
    INTERACTION = "interaction"
    SUPPORT = "support"


class TrustLevel(StrEnum):
    CORE = "core"
    PROJECT = "project"
    THIRD_PARTY = "third_party"


class RetryMode(StrEnum):
    NEVER = "never"
    TRANSIENT_ONCE = "transient_once"


class CapabilityPermissions(ContractModel):
    read: list[NonEmptyString] = Field(default_factory=list)
    write: list[NonEmptyString] = Field(default_factory=list)


class CapabilityFailurePolicy(ContractModel):
    retry: RetryMode = RetryMode.NEVER
    fallback: NonEmptyString = "return_typed_failure"


class CapabilityIndexEntry(ContractModel):
    id: CapabilityId
    version: SemanticVersion
    kind: CapabilityKind
    role: CapabilityRole
    description: Annotated[str, Field(min_length=40)]
    entrypoint: NonEmptyString | None = None
    input_schema: NonEmptyString | None = None
    output_schema: NonEmptyString | None = None
    intents: list[NonEmptyString] = Field(min_length=1)
    required_context: list[NonEmptyString] = Field(default_factory=list)
    permissions: CapabilityPermissions
    preconditions: list[NonEmptyString] = Field(default_factory=list)
    dependencies: list[CapabilityId] = Field(default_factory=list)
    produces: list[NonEmptyString] = Field(default_factory=list)
    verifiers: list[CapabilityId] = Field(default_factory=list)
    failure_policy: CapabilityFailurePolicy = Field(default_factory=CapabilityFailurePolicy)
    trust: TrustLevel

    @model_validator(mode="after")
    def validate_kind_boundary(self) -> "CapabilityIndexEntry":
        if self.entrypoint is None:
            raise ValueError("all entries require an entrypoint")
        if self.kind in {CapabilityKind.CAPABILITY, CapabilityKind.LENS} and (
            self.input_schema is None or self.output_schema is None
        ):
            raise ValueError("executable entries require input_schema and output_schema")
        if self.kind in {CapabilityKind.POLICY, CapabilityKind.PROMPT_PACK} and (
            self.permissions.write
        ):
            raise ValueError("non-executable entries cannot write")
        return self


class CapabilityIndexDocument(ContractModel):
    entries: list[CapabilityIndexEntry]


class CapabilityRegistrySnapshot(ContractModel):
    entries: list[CapabilityIndexEntry]
    digest: Digest

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "CapabilityRegistrySnapshot":
        ids = [entry.id for entry in self.entries]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate capability id")
        return self
