"""Ports owned by the read-only Job Intelligence subsystem."""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from jobagent.schemas.job_intelligence import JobSearchQuery, SourceJobRecord
from jobagent.schemas.jobs import (
    HardFilterResult,
    JobRequirementProfile,
    MatchResult,
    NormalizedJob,
    RecruiterInfo,
)


@runtime_checkable
class JobDiscoverySource(Protocol):
    def search(self, query: JobSearchQuery) -> Sequence[SourceJobRecord]: ...

    def fetch_job(self, source_job_id: str) -> SourceJobRecord: ...

    def get_recruiter(self, source_job_id: str) -> RecruiterInfo | None: ...


@runtime_checkable
class JobRepository(Protocol):
    def save_job(self, job: NormalizedJob) -> None: ...

    def get_job(self, job_id: str) -> NormalizedJob | None: ...

    def list_jobs(self) -> list[NormalizedJob]: ...

    def save_requirements(self, profile: JobRequirementProfile) -> str: ...

    def get_requirements(self, job_id: str) -> JobRequirementProfile | None: ...

    def save_filter_result(
        self,
        candidate_id: str,
        job_id: str,
        policy_digest: str,
        result: HardFilterResult,
    ) -> None: ...

    def get_filter_result(
        self,
        candidate_id: str,
        job_id: str,
        policy_digest: str,
    ) -> HardFilterResult | None: ...

    def save_match(
        self,
        candidate_id: str,
        job_id: str,
        *,
        evidence_digest: str,
        requirements_digest: str,
        policy_digest: str,
        result: MatchResult,
    ) -> None: ...

    def get_match(
        self,
        candidate_id: str,
        job_id: str,
        *,
        evidence_digest: str,
        requirements_digest: str,
        policy_digest: str,
    ) -> MatchResult | None: ...
