"""Ports owned by the read-only Job Intelligence subsystem."""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from jobagent.schemas.job_intelligence import JobSearchQuery, SourceJobRecord
from jobagent.schemas.jobs import RecruiterInfo


@runtime_checkable
class JobDiscoverySource(Protocol):
    def search(self, query: JobSearchQuery) -> Sequence[SourceJobRecord]: ...

    def fetch_job(self, source_job_id: str) -> SourceJobRecord: ...

    def get_recruiter(self, source_job_id: str) -> RecruiterInfo | None: ...
