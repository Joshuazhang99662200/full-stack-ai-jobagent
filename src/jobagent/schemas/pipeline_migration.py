"""Explicit private legacy-to-pipeline mapping; no personal batch defaults."""

from typing import Literal

from pydantic import AwareDatetime, Field, HttpUrl, model_validator

from jobagent.schemas.candidate import CandidateId
from jobagent.schemas.common import ContractModel, Digest, NonEmptyString
from jobagent.schemas.host_migration import MigrationKey


class PipelineMigrationFields(ContractModel):
    row_id: str = "id"
    candidate_id: str = "candidate_id"
    platform: str = "platform"
    job_id: str = "job_id"
    source_job_id: str = "source_job_id"
    job_url: str = "job_url"
    title: str = "title"
    company: str = "company"
    location: str = "location"
    salary_raw: str = "salary_raw"
    jd_points: str = "jd_points"
    jd_summary: str = "jd_summary"
    draft_greeting: str = "draft_greeting"
    draft_version: str = "draft_version"
    draft_digest: str = "draft_digest"
    entered_at: str = "entered_at"


class PipelineMigrationConfig(ContractModel):
    migration_id: MigrationKey
    candidate_id: CandidateId
    domain: NonEmptyString
    expected_count: int = Field(ge=1, le=10000)
    expected_row_ids: list[str] = Field(min_length=1, max_length=10000)
    fields: PipelineMigrationFields = Field(default_factory=PipelineMigrationFields)
    platform_values: dict[str, str] = Field(default_factory=dict)
    job_id_mode: Literal["preserve", "platform_source_id"] = "preserve"
    job_id_prefixes: dict[str, str] = Field(
        default_factory=lambda: {"boss": "boss-", "zhaopin": "zhaopin-"}
    )
    sent_row_ids: list[str] = Field(default_factory=list)
    derived_entered_at: AwareDatetime | None = None
    derived_entered_at_by_row: dict[str, AwareDatetime] = Field(default_factory=dict)
    derived_evidence_reference: NonEmptyString | None = None
    salary_minimum_k: int = Field(ge=0)
    salary_currency: str = Field(default="CNY", min_length=3, max_length=3)

    @model_validator(mode="after")
    def explicit_batch(self) -> "PipelineMigrationConfig":
        if len(self.expected_row_ids) != self.expected_count:
            raise ValueError("Expected original IDs must match the explicit row count.")
        if len(set(self.expected_row_ids)) != len(self.expected_row_ids):
            raise ValueError("Expected original IDs cannot repeat.")
        if len(set(self.sent_row_ids)) != len(self.sent_row_ids):
            raise ValueError("Historical send declarations cannot repeat.")
        if not set(self.sent_row_ids) <= set(self.expected_row_ids):
            raise ValueError("Send declarations must refer to explicit original rows.")
        if not set(self.derived_entered_at_by_row) <= set(self.expected_row_ids):
            raise ValueError("Derived times must refer to original rows.")
        if (
            self.derived_entered_at or self.derived_entered_at_by_row
        ) and not self.derived_evidence_reference:
            raise ValueError("Derived entry times need their actual private round evidence.")
        return self


class PipelineMappedLegacyRow(ContractModel):
    row_id: str
    platform: Literal["boss", "zhaopin"]
    job_id: str | None
    provider_id: str | None
    job_url: HttpUrl | None
    title: str | None
    company: str | None
    location: str | None
    salary_raw: str
    jd_points: list[str] = Field(max_length=3)
    draft_greeting: str | None = Field(repr=False)
    draft_version: str | None
    entered_at: AwareDatetime | None
    entered_time_basis: Literal["observed", "derived", "unknown_legacy"]
    entry_evidence_reference: str
    source_line: str = Field(repr=False)
    source_digest: Digest
    source_json: dict[str, object] = Field(repr=False)
