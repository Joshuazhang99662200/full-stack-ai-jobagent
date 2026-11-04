"""Read-only public ATS observations, budgets and candidate-scoped projections."""

from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from jobagent.schemas.candidate import CandidateId
from jobagent.schemas.common import ContractModel, Digest, NonEmptyString
from jobagent.schemas.job_intelligence import CandidateFilterContext, JobListing, SourceJobRecord
from jobagent.schemas.jobs import JobId


class PublicCareerBoard(ContractModel):
    provider: Literal["greenhouse", "ashby"]
    board: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    company: NonEmptyString

    @property
    def source(self) -> str:
        return f"public_careers:{self.provider}:{self.board}"

    @property
    def api_url(self) -> str:
        if self.provider == "greenhouse":
            return f"https://boards-api.greenhouse.io/v1/boards/{self.board}/jobs?content=true"
        return f"https://api.ashbyhq.com/posting-api/job-board/{self.board}"


class PublicCareerConfig(ContractModel):
    boards: list[PublicCareerBoard] = Field(min_length=1, max_length=100)
    filter_context: CandidateFilterContext

    @model_validator(mode="after")
    def unique_boards(self) -> "PublicCareerConfig":
        if len({b.source for b in self.boards}) != len(self.boards):
            raise ValueError("Duplicate public boards.")
        return self


class PublicCareerItem(ContractModel):
    input_index: int = Field(default=0, ge=0)
    listing: JobListing
    observation: SourceJobRecord | None = None


class PublicCareerPage(ContractModel):
    records: list[PublicCareerItem] = Field(default_factory=list)
    raw_returned: int = Field(default=0, ge=0)
    missing_jd: int = Field(default=0, ge=0)
    invalid: int = Field(default=0, ge=0)
    truncated: bool = False


class PublicCareerRecord(ContractModel):
    candidate_id: CandidateId
    channel: Literal["public_careers"] = "public_careers"
    provider: Literal["greenhouse", "ashby"]
    board: NonEmptyString
    source_job_id: NonEmptyString
    job_id: JobId
    run_id: NonEmptyString
    listing: JobListing
    observation: SourceJobRecord | None = None
    region_decision: Literal["pass", "review", "reject"]

    @model_validator(mode="after")
    def consistent_identity(self) -> "PublicCareerRecord":
        import hashlib

        source = f"public_careers:{self.provider}:{self.board}"
        expected = (
            "JOB_"
            + hashlib.sha256(f"{source.casefold()}\0{self.source_job_id.casefold()}".encode())
            .hexdigest()[:16]
            .upper()
        )
        if (
            self.listing.source != source
            or self.listing.source_job_id != self.source_job_id
            or self.job_id != expected
        ):
            raise ValueError("Public posting identity does not match configured source.")
        observed = self.observation
        if observed and (
            observed.source != source
            or observed.source_job_id != self.source_job_id
            or observed.url != self.listing.url
        ):
            raise ValueError("Public observation does not match listing identity.")
        return self


class PublicCareerRun(ContractModel):
    run_id: NonEmptyString
    candidate_id: CandidateId
    channel: Literal["public_careers"] = "public_careers"
    rules_version: Digest
    started_at: AwareDatetime
    status: Literal["running", "complete", "partial", "failed", "paused", "cancelled"] = "running"
    boards_completed: list[str] = Field(default_factory=list)
    resume_board: str | None = None
    query_attempts: int = Field(default=0, ge=0)
    http_attempts: int = Field(default=0, ge=0)
    detail_attempts: int = Field(default=0, ge=0)
    raw_returned: int = Field(default=0, ge=0)
    observed: int = Field(default=0, ge=0)
    eligible: int = Field(default=0, ge=0)
    taken: int = Field(default=0, ge=0)
    duplicate: int = Field(default=0, ge=0)
    missing_jd: int = Field(default=0, ge=0)
    invalid: int = Field(default=0, ge=0)
    errors: list[str] = Field(default_factory=list)
    budgets: dict[str, int] = Field(default_factory=dict)
    config: PublicCareerConfig | None = None
    dispositions: list["PublicCareerDisposition"] = Field(default_factory=list)
    grants_delivery_permission: Literal[False] = False


class PublicCareerDisposition(ContractModel):
    source: NonEmptyString
    input_index: int = Field(ge=0)
    source_job_id: str | None = None
    disposition: Literal["invalid", "rejected", "deferred", "taken", "duplicate"]
