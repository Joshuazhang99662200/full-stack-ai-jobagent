"""Explicit legacy field mapping; summaries and unverified sends never become proof."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, HttpUrl, StringConstraints

from jobagent.schemas.candidate import CandidateId
from jobagent.schemas.common import ContractModel, Digest
from jobagent.schemas.job_intake import IntakeSnapshot

MigrationKey = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,80}$")]


class LegacyFieldMap(ContractModel):
    row_id: str = "id"
    platform: str = "source"
    job_url: str = "url"
    source_job_id: str = "source_job_id"
    title: str = "title"
    company: str = "company"
    location: str = "location"
    summary: str = "jd_summary"
    status: str = "status"
    send_reference: str = "send_reference"
    observed_at: str = "collected_at"


class QueueMigrationConfig(ContractModel):
    migration_id: MigrationKey
    candidate_id: CandidateId
    domain: str = Field(min_length=1)
    expected_count: int = Field(default=40, ge=1, le=10000)
    fields: LegacyFieldMap = Field(default_factory=LegacyFieldMap)
    platform_values: dict[str, str] = Field(default_factory=dict)
    sent_row_ids: list[str] = Field(default_factory=list)
    sent_row_id_field: str = "row_id"
    sent_send_reference_field: str = "send_reference"
    expected_sent_count: int | None = Field(default=None, ge=0, le=10000)
    require_distinct_jobs: bool = True
    priority_ids: list[str] = Field(default_factory=list)


class LegacyMappedRow(ContractModel):
    row_id: str = Field(min_length=1)
    platform: str = Field(min_length=1)
    job_url: HttpUrl
    source_job_id: str | None = None
    title: str | None = None
    company: str | None = None
    location: str | None = None
    summary: str = ""
    legacy_status: str | None = None
    observed_at: AwareDatetime | None = None
    source_line: str = Field(repr=False)
    source_digest: Digest
    source_json: dict[str, object] = Field(repr=False)


class LegacyPartialSnapshot(ContractModel):
    legacy_snapshot_id: Digest
    snapshot_version: Literal[0] = 0
    full_jd_text_stored: Literal[False] = False
    observed_at: AwareDatetime | None = None
    imported_at: AwareDatetime
    summary: str = Field(repr=False)


class LegacyTrackingBinding(ContractModel):
    migration_id: MigrationKey
    row_id: str
    candidate_id: CandidateId
    tracking_id: str


class LegacyBackfillBinding(ContractModel):
    migration_id: MigrationKey
    row_id: str
    candidate_id: CandidateId
    snapshot: IntakeSnapshot
