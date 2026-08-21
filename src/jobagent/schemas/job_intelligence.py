"""Serialized contracts for read-only Job Intelligence workflows."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, HttpUrl, model_validator

from jobagent.schemas.candidate import CandidateId, EvidenceId
from jobagent.schemas.common import ContractModel, MoneyRange, NonEmptyString
from jobagent.schemas.jobs import (
    FilterDecision,
    HardFilterResult,
    JobId,
    JobRequirementProfile,
    MatchDecision,
    MatchResult,
    NormalizedJob,
    RecruiterInfo,
    RequirementId,
)


class SourceJobRecord(ContractModel):
    source: NonEmptyString
    source_job_id: NonEmptyString
    title: NonEmptyString
    company: NonEmptyString
    location: NonEmptyString
    salary_text: str | None = None
    jd_raw: NonEmptyString
    recruiter: RecruiterInfo | None = None
    url: HttpUrl
    published_at: datetime | None = None
    collected_at: datetime


class JobSearchQuery(ContractModel):
    query: str = ""
    title: str | None = None
    company: str | None = None
    location: str | None = None
    source_job_id: str | None = None


class DeduplicationPolicy(ContractModel):
    near_duplicate_threshold: Annotated[float, Field(ge=0, le=1)] = 0.85


class DuplicateGroup(ContractModel):
    canonical_job_id: JobId
    member_job_ids: list[JobId] = Field(min_length=2)
    reason: NonEmptyString

    @model_validator(mode="after")
    def require_unique_members(self) -> "DuplicateGroup":
        if len(set(self.member_job_ids)) != len(self.member_job_ids):
            raise ValueError("duplicate-group member IDs must be unique")
        return self


class DeduplicationResult(ContractModel):
    jobs: list[NormalizedJob]
    duplicate_groups: list[DuplicateGroup] = Field(default_factory=list)


class CandidateFilterContext(ContractModel):
    candidate_id: CandidateId
    allowed_locations: list[str] = Field(default_factory=list)
    remote_allowed: bool | None = None
    work_authorized_locations: list[str] = Field(default_factory=list)
    languages: dict[str, str] = Field(default_factory=dict)
    education_levels: list[str] = Field(default_factory=list)
    minimum_compensation: MoneyRange | None = None
    excluded_role_terms: list[str] = Field(default_factory=list)


class HardFilterPolicy(ContractModel):
    enabled_rule_ids: list[str] = Field(
        default_factory=lambda: [
            "LOCATION_HARD_CONSTRAINT",
            "WORK_AUTHORIZATION",
            "LANGUAGE_HARD_REQUIREMENT",
            "EDUCATION_HARD_REQUIREMENT",
            "COMPENSATION_MINIMUM",
            "ROLE_EXCLUSION",
        ]
    )
    review_on_unknown: bool = True


class RequirementMatchOutcome(StrEnum):
    SUPPORTED = "supported"
    PARTIAL = "partial"
    MISSING = "missing"
    UNCERTAIN = "uncertain"


class RequirementEvidenceMatch(ContractModel):
    requirement_id: RequirementId
    outcome: RequirementMatchOutcome
    evidence_ids: list[EvidenceId] = Field(default_factory=list)
    explanation: NonEmptyString
    uncertainty: str | None = None

    @model_validator(mode="after")
    def supported_requires_evidence(self) -> "RequirementEvidenceMatch":
        if self.outcome is RequirementMatchOutcome.SUPPORTED and not self.evidence_ids:
            raise ValueError("supported requirement match requires evidence")
        return self


class RequirementMatchSet(ContractModel):
    job_id: JobId
    candidate_id: CandidateId
    matches: list[RequirementEvidenceMatch]

    @model_validator(mode="after")
    def require_unique_requirement_ids(self) -> "RequirementMatchSet":
        requirement_ids = [match.requirement_id for match in self.matches]
        if len(set(requirement_ids)) != len(requirement_ids):
            raise ValueError("requirement match IDs must be unique")
        return self


class MatchThresholdPolicy(ContractModel):
    strong: Annotated[float, Field(ge=0, le=1)] = 0.8
    possible: Annotated[float, Field(ge=0, le=1)] = 0.6
    weak: Annotated[float, Field(ge=0, le=1)] = 0.35

    @model_validator(mode="after")
    def require_descending_thresholds(self) -> "MatchThresholdPolicy":
        if not self.strong > self.possible > self.weak:
            raise ValueError("match thresholds must descend: strong > possible > weak")
        return self


class JobIntelligencePolicies(ContractModel):
    deduplication: DeduplicationPolicy = Field(default_factory=DeduplicationPolicy)
    hard_filter: HardFilterPolicy = Field(default_factory=HardFilterPolicy)
    match_thresholds: MatchThresholdPolicy = Field(default_factory=MatchThresholdPolicy)


class JobAssessment(ContractModel):
    job_id: JobId
    filter_result: HardFilterResult
    match_result: MatchResult
    published_at: datetime | None = None
    must_have_score: Annotated[float, Field(ge=0, le=1)] = 0.0


class RankedJob(ContractModel):
    job_id: JobId
    rank: Annotated[int, Field(ge=1)]
    filter_decision: FilterDecision
    match_decision: MatchDecision
    overall: Annotated[float, Field(ge=0, le=1)]
    must_have_score: Annotated[float, Field(ge=0, le=1)]
    application_ready: Literal[False] = False
    explanation: NonEmptyString


class JobIntelligenceRun(ContractModel):
    candidate_id: CandidateId
    query: JobSearchQuery
    normalized_jobs: list[NormalizedJob]
    requirements: list[JobRequirementProfile]
    filter_results: dict[str, HardFilterResult]
    matches: dict[str, MatchResult]
    ranked_jobs: list[RankedJob]
