"""Small, source-bound preference notes, not candidate facts or permissions."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import Field, model_validator

from jobagent.schemas.candidate import CandidateId
from jobagent.schemas.common import ContractModel, Digest, NonEmptyString
from jobagent.schemas.jobs import JobId


class PreferenceRule(ContractModel):
    rule_id: NonEmptyString
    category: Literal["jobs", "greetings"]
    scope: Literal["general", "role", "job"]
    condition: Annotated[str, Field(min_length=1, max_length=500)]
    job_id: JobId | None = None
    text: Annotated[str, Field(min_length=1, max_length=500)]
    source_event_ids: list[NonEmptyString] = Field(min_length=1, max_length=30)
    updated_at: datetime

    @model_validator(mode="after")
    def validate_scope(self) -> "PreferenceRule":
        if (self.scope == "job") != (self.job_id is not None):
            raise ValueError("Only job-specific preferences bind an individual JD.")
        if len(set(self.source_event_ids)) != len(self.source_event_ids):
            raise ValueError("Preference sources must be unique.")
        return self


class PreferenceMemory(ContractModel):
    candidate_id: CandidateId
    version: NonEmptyString = "PMEM_EMPTY"
    previous_version: str | None = None
    consumed_event_ids: list[NonEmptyString] = Field(default_factory=list)
    rules: list[PreferenceRule] = Field(default_factory=list, max_length=24)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_provenance(self) -> "PreferenceMemory":
        ids = [rule.rule_id for rule in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("Preference rule IDs must be unique.")
        if len(self.consumed_event_ids) != len(set(self.consumed_event_ids)):
            raise ValueError("Consumed events must be unique.")
        if any(not set(rule.source_event_ids) <= set(self.consumed_event_ids)
               for rule in self.rules):
            raise ValueError("Every preference needs consumed source events.")
        return self


class PreferenceUpdate(ContractModel):
    input_digest: Digest
    rules: list[PreferenceRule] = Field(default_factory=list, max_length=24)


class PreferenceApplication(ContractModel):
    input_digest: Digest
    selected_rule_ids: list[NonEmptyString] = Field(default_factory=list, max_length=24)
    search_queries: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        default_factory=list, max_length=12,
    )


class PreferenceSelection(ContractModel):
    memory_version: NonEmptyString
    memory_digest: Digest
    rules: list[PreferenceRule] = Field(default_factory=list, max_length=24)
    search_queries: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        default_factory=list, max_length=12,
    )
