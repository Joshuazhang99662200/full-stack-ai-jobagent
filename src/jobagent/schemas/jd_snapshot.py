"""Immutable JD content and separately attributable discoveries."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, HttpUrl, StringConstraints, model_validator

from jobagent.schemas.common import ContractModel, Digest
from jobagent.schemas.jobs import JobId

SnapshotKey = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class JDSnapshotInput(ContractModel):
    observation_id: SnapshotKey
    job_id: JobId
    job_url: HttpUrl
    platform: SnapshotKey
    fetched_at: AwareDatetime
    query_hit: SnapshotKey | None = None
    discovery_kind: Literal["search", "manual", "recommendation", "unknown"] = "unknown"
    title: SnapshotKey
    company: SnapshotKey
    location: str | None = None
    salary_raw: str | None = None
    jd_text: str
    completeness: Literal["full", "listing", "partial"]

    @model_validator(mode="after")
    def check_capture(self) -> "JDSnapshotInput":
        if self.discovery_kind == "search" and self.query_hit is None:
            raise ValueError("Search discoveries require the actual query.")
        if self.discovery_kind != "search" and self.query_hit is not None:
            raise ValueError("A non-search discovery cannot invent a query.")
        if self.completeness == "full" and not self.jd_text.strip():
            raise ValueError("A full snapshot must contain JD text.")
        return self


class JDSnapshot(JDSnapshotInput):
    snapshot_id: SnapshotKey
    jd_text_hash: Digest
    content_digest: Digest
    snapshot_version: Annotated[int, Field(ge=1)]


class SnapshotDiscovery(ContractModel):
    observation_id: SnapshotKey
    snapshot_id: SnapshotKey
    job_id: JobId
    fetched_at: AwareDatetime
    query_hit: SnapshotKey | None
    discovery_kind: Literal["search", "manual", "recommendation", "unknown"]


class SnapshotCaptureResult(ContractModel):
    snapshot: JDSnapshot
    discovery: SnapshotDiscovery
    created: bool
