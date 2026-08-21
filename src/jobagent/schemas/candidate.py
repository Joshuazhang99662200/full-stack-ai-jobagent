"""Candidate knowledge-base and evidence contracts."""

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any

from pydantic import Field, model_validator

from jobagent.schemas.common import ContractModel, NonEmptyString, SourceReference, TimeRange

EvidenceId = Annotated[str, Field(pattern=r"^EVID_[A-Z0-9_]+$")]
CandidateId = Annotated[str, Field(pattern=r"^CAND_[A-Z0-9_]+$")]
EntityId = Annotated[str, Field(pattern=r"^[A-Z]+_[A-Z0-9_]+$")]


class EvidenceType(StrEnum):
    ACHIEVEMENT = "achievement"
    EXPERIENCE = "experience"
    SKILL = "skill"
    PROJECT = "project"
    EDUCATION = "education"
    MANAGEMENT = "management"
    COMMERCIAL = "commercial"
    DOMAIN = "domain"
    LANGUAGE = "language"
    CERTIFICATION = "certification"


class Confidence(StrEnum):
    EXPLICIT = "explicit"
    INFERRED = "inferred"
    WEAK = "weak"


class MetricFact(ContractModel):
    name: NonEmptyString
    value: Decimal
    unit: NonEmptyString
    population: str | None = None
    time_window: str | None = None


class EvidenceItem(ContractModel):
    id: EvidenceId
    type: EvidenceType
    entity: str = ""
    statement: NonEmptyString
    skills: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    metrics: list[MetricFact] = Field(default_factory=list)
    time_range: TimeRange | None = None
    source: SourceReference
    confidence: Confidence
    user_confirmed: bool = False

    @model_validator(mode="after")
    def reject_confirmed_weak_evidence(self) -> "EvidenceItem":
        if self.user_confirmed and self.confidence is Confidence.WEAK:
            raise ValueError("weak evidence cannot be marked user-confirmed")
        return self


class Experience(ContractModel):
    id: EntityId
    company: NonEmptyString
    title: NonEmptyString
    time_range: TimeRange
    location: str | None = None
    summary: str | None = None
    evidence_ids: list[EvidenceId] = Field(default_factory=list)


class Education(ContractModel):
    id: EntityId
    institution: NonEmptyString
    degree: str | None = None
    field_of_study: str | None = None
    time_range: TimeRange | None = None
    evidence_ids: list[EvidenceId] = Field(default_factory=list)


class Skill(ContractModel):
    name: NonEmptyString
    level: str | None = None
    evidence_ids: list[EvidenceId] = Field(default_factory=list)


class Project(ContractModel):
    id: EntityId
    name: NonEmptyString
    statement: NonEmptyString
    time_range: TimeRange | None = None
    evidence_ids: list[EvidenceId] = Field(default_factory=list)


class Achievement(ContractModel):
    id: EntityId
    statement: NonEmptyString
    evidence_ids: list[EvidenceId] = Field(min_length=1)


class DomainExperience(ContractModel):
    domain: NonEmptyString
    years: Annotated[Decimal, Field(ge=0)] | None = None
    evidence_ids: list[EvidenceId] = Field(min_length=1)


class ManagementExperience(ContractModel):
    scope: NonEmptyString
    team_size: Annotated[int, Field(ge=1)] | None = None
    evidence_ids: list[EvidenceId] = Field(min_length=1)


class CommercialExperience(ContractModel):
    scope: NonEmptyString
    evidence_ids: list[EvidenceId] = Field(min_length=1)


class Language(ContractModel):
    name: NonEmptyString
    proficiency: NonEmptyString
    evidence_ids: list[EvidenceId] = Field(default_factory=list)


class Certification(ContractModel):
    name: NonEmptyString
    issuer: str | None = None
    awarded_at: date | None = None
    evidence_ids: list[EvidenceId] = Field(default_factory=list)


class Preference(ContractModel):
    key: NonEmptyString
    value: Any


class Constraint(ContractModel):
    key: NonEmptyString
    value: Any
    hard: bool = True


class UnknownField(ContractModel):
    path: NonEmptyString
    reason: NonEmptyString
    target_role_relevance: Annotated[float, Field(ge=0, le=1)] = 0.0


class GapPriority(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class CandidateGap(ContractModel):
    id: EntityId
    field_path: NonEmptyString
    reason: NonEmptyString
    priority: GapPriority
    target_role: str | None = None
    suggested_question: str | None = None


class CandidateReadinessReport(ContractModel):
    profile_completeness: Annotated[float, Field(ge=0, le=1)]
    high_value_gaps: list[CandidateGap] = Field(default_factory=list)
    weak_claim_evidence_ids: list[EvidenceId] = Field(default_factory=list)
    confirmed_evidence_count: Annotated[int, Field(ge=0)]
    target_role_readiness: Annotated[float, Field(ge=0, le=1)]


class CandidateProfile(ContractModel):
    id: CandidateId
    full_name: str | None = None
    headline: str | None = None
    experiences: list[Experience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    skills: list[Skill] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    achievements: list[Achievement] = Field(default_factory=list)
    domain_experience: list[DomainExperience] = Field(default_factory=list)
    management_experience: list[ManagementExperience] = Field(default_factory=list)
    commercial_experience: list[CommercialExperience] = Field(default_factory=list)
    languages: list[Language] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)
    preferences: list[Preference] = Field(default_factory=list)
    constraints: list[Constraint] = Field(default_factory=list)
    unknown_fields: list[UnknownField] = Field(default_factory=list)
