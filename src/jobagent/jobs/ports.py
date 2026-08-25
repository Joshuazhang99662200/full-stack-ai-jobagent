"""Ports owned by the read-only Job Intelligence subsystem."""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from jobagent.schemas.candidate import EvidenceItem
from jobagent.schemas.job_intelligence import (
    JobListing,
    JobSearchQuery,
    RequirementMatchSet,
    SourceJobRecord,
)
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
class JobListingSource(Protocol):
    """A source whose result pages expose no JD text.

    Kept separate from ``JobDiscoverySource`` on purpose: such a source cannot
    produce a ``SourceJobRecord``, and must not be allowed to synthesize one.
    """

    def search_listings(self, query: JobSearchQuery) -> Sequence[JobListing]: ...


@runtime_checkable
class JobDetailFetcher(Protocol):
    """Turn a listing into a full observation by reading the posting itself."""

    def fetch(self, listing: JobListing) -> SourceJobRecord: ...


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


@runtime_checkable
class JobRequirementExtractor(Protocol):
    def extract(self, job: NormalizedJob) -> JobRequirementProfile: ...


@runtime_checkable
class JobEvidenceMatcher(Protocol):
    def map(
        self,
        job: NormalizedJob,
        requirements: JobRequirementProfile,
        candidate_id: str,
        evidence: Sequence[EvidenceItem],
    ) -> RequirementMatchSet: ...
