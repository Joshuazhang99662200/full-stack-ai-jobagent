"""Normalized job, requirement, filter, and match contracts."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import Field, HttpUrl, model_validator

from jobagent.schemas.candidate import EvidenceId
from jobagent.schemas.common import ContractModel, MoneyRange, NonEmptyString, ProvenanceRecord

JobId = Annotated[str, Field(pattern=r"^JOB_[A-Z0-9_]+$")]
RequirementId = Annotated[str, Field(pattern=r"^REQ_[A-Z0-9_]+$")]


class RecruiterType(StrEnum):
    """Who is on the other side of the conversation.

    `INTERNAL_UNSPECIFIED` is a real answer, not a placeholder: a listing often
    proves the recruiter is employer-side without revealing whether they are HR
    or the hiring manager. Collapsing that into a guess would route a rewrite on
    an invented distinction.
    """

    HEADHUNTER = "headhunter"
    HR = "hr"
    HIRING_MANAGER = "hiring_manager"
    INTERNAL_UNSPECIFIED = "internal_unspecified"
    UNKNOWN = "unknown"


class RecruiterInfo(ContractModel):
    name: str | None = None
    title: str | None = None
    contact_channel: str | None = None
    organization: str | None = None
    type: RecruiterType = RecruiterType.UNKNOWN
    # Inferred, never observed. Routing must gate on this rather than trust `type`.
    type_confidence: Annotated[float, Field(ge=0, le=1)] = 0.0
    type_signals: list[str] = Field(default_factory=list)


class NormalizedJob(ContractModel):
    id: JobId
    source: NonEmptyString
    source_job_id: NonEmptyString
    title: NonEmptyString
    company: NonEmptyString
    location: NonEmptyString
    salary: MoneyRange | None = None
    jd_raw: NonEmptyString
    recruiter: RecruiterInfo | None = None
    url: HttpUrl
    published_at: datetime | None = None
    collected_at: datetime
    provenance: list[ProvenanceRecord] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)


class RequirementPriority(StrEnum):
    MUST = "must"
    PREFERRED = "preferred"
    CONTEXT = "context"
    UNCERTAIN = "uncertain"


class JobRequirement(ContractModel):
    id: RequirementId
    statement: NonEmptyString
    category: NonEmptyString
    priority: RequirementPriority
    source_span: NonEmptyString
    keywords: list[str] = Field(default_factory=list)
    confidence: Annotated[float, Field(ge=0, le=1)] = 1.0


class JobRequirementProfile(ContractModel):
    job_id: JobId
    requirements: list[JobRequirement] = Field(default_factory=list)
    must_have: list[str] = Field(default_factory=list)
    nice_to_have: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    seniority: str | None = None
    management: list[str] = Field(default_factory=list)
    commercial: list[str] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    location_constraints: list[str] = Field(default_factory=list)
    risk_signals: list[str] = Field(default_factory=list)


class FilterDecision(StrEnum):
    PASS = "pass"
    REVIEW = "review"
    REJECT = "reject"


class FilterReason(ContractModel):
    rule_id: NonEmptyString
    message: NonEmptyString
    observed_value: str | None = None
    required_value: str | None = None


class HardFilterResult(ContractModel):
    decision: FilterDecision
    reasons: list[FilterReason] = Field(default_factory=list)

    @model_validator(mode="after")
    def reject_requires_reason(self) -> "HardFilterResult":
        if self.decision is FilterDecision.REJECT and not self.reasons:
            raise ValueError("a rejected job requires at least one deterministic reason")
        return self


class MatchDecision(StrEnum):
    STRONG_MATCH = "strong_match"
    POSSIBLE_MATCH = "possible_match"
    WEAK_MATCH = "weak_match"
    NOT_A_MATCH = "not_a_match"


class DimensionScore(ContractModel):
    dimension: NonEmptyString
    score: Annotated[float, Field(ge=0, le=1)]
    explanation: NonEmptyString
    evidence_ids: list[EvidenceId] = Field(default_factory=list)


class MatchResult(ContractModel):
    overall: Annotated[float, Field(ge=0, le=1)]
    decision: MatchDecision
    dimensions: list[DimensionScore] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    partial_matches: list[str] = Field(default_factory=list)
    hard_gaps: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    evidence_ids: list[EvidenceId] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_explanation(self) -> "MatchResult":
        lanes = (
            self.dimensions,
            self.strengths,
            self.partial_matches,
            self.hard_gaps,
            self.uncertainties,
        )
        if not any(lanes):
            raise ValueError("match result requires at least one explanatory lane")
        return self
