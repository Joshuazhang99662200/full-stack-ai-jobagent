"""Candidate knowledge-base and evidence contracts."""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any

from pydantic import Field, model_validator

from jobagent.schemas.common import (
    ContractModel,
    Digest,
    NonEmptyString,
    SourceReference,
    TimeRange,
)

EvidenceId = Annotated[str, Field(pattern=r"^EVID_[A-Z0-9_]+$")]
CandidateId = Annotated[str, Field(pattern=r"^CAND_[A-Z0-9_]+$")]
EntityId = Annotated[str, Field(pattern=r"^[A-Z]+_[A-Z0-9_]+$")]
ResumeId = Annotated[str, Field(pattern=r"^RESUME_[A-Z0-9_]+$")]
QuestionId = Annotated[str, Field(pattern=r"^QUESTION_[A-Z0-9_]+$")]


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


# A concrete union rather than Any: these models are emitted by structured model
# output, and an untyped schema node is rejected by strict JSON-schema validation.
SettingValue = str | bool | int | float | list[str]


class Preference(ContractModel):
    key: NonEmptyString
    value: SettingValue


class Constraint(ContractModel):
    key: NonEmptyString
    value: SettingValue
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


class ResumePage(ContractModel):
    page_number: Annotated[int, Field(ge=1)]
    text: str
    warnings: list[str] = Field(default_factory=list)


class ParsedResume(ContractModel):
    id: ResumeId
    candidate_id: CandidateId
    source_name: NonEmptyString
    media_type: str = "application/pdf"
    content_digest: Digest
    pages: list[ResumePage] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_ordered_unique_pages(self) -> "ParsedResume":
        page_numbers = [page.page_number for page in self.pages]
        if page_numbers != sorted(set(page_numbers)):
            raise ValueError("resume pages must have unique ascending page numbers")
        return self


class CandidateDraft(ContractModel):
    candidate_id: CandidateId
    profile: CandidateProfile
    evidence: list[EvidenceItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_candidate_and_evidence_references(self) -> "CandidateDraft":
        if self.profile.id != self.candidate_id:
            raise ValueError("draft candidate_id must match profile.id")
        if any(item.user_confirmed for item in self.evidence):
            raise ValueError("draft evidence cannot be user-confirmed")

        available_ids = {item.id for item in self.evidence}
        referenced_ids: set[str] = set()
        evidence_bearing_groups = (
            self.profile.experiences,
            self.profile.education,
            self.profile.skills,
            self.profile.projects,
            self.profile.achievements,
            self.profile.domain_experience,
            self.profile.management_experience,
            self.profile.commercial_experience,
            self.profile.languages,
            self.profile.certifications,
        )
        for group in evidence_bearing_groups:
            for item in group:
                referenced_ids.update(item.evidence_ids)
        missing_ids = sorted(referenced_ids - available_ids)
        if missing_ids:
            raise ValueError(f"profile references missing draft evidence: {missing_ids}")
        return self


class InterviewQuestion(ContractModel):
    id: QuestionId
    candidate_id: CandidateId
    primary_gap_id: EntityId
    text: NonEmptyString
    reason: NonEmptyString
    expected_information: NonEmptyString
    score: Annotated[float, Field(ge=0, le=1)]


class InterviewAnswer(ContractModel):
    question_id: QuestionId
    answer: NonEmptyString | None = None
    skipped: bool = False

    @model_validator(mode="after")
    def require_answer_or_skip(self) -> "InterviewAnswer":
        if self.skipped == (self.answer is not None):
            raise ValueError("provide an answer or mark the question skipped")
        return self


class InterviewEventType(StrEnum):
    QUESTION = "question"
    ANSWER = "answer"
    SKIP = "skip"


class InterviewEvent(ContractModel):
    id: EntityId
    candidate_id: CandidateId
    event_type: InterviewEventType
    question_id: QuestionId
    payload: dict[str, Any]
    created_at: datetime


class InterviewOutcome(ContractModel):
    event: InterviewEvent
    draft_evidence: EvidenceItem | None = None

    @model_validator(mode="after")
    def validate_event_evidence_pair(self) -> "InterviewOutcome":
        if self.event.event_type is InterviewEventType.ANSWER and self.draft_evidence is None:
            raise ValueError("answered interview event requires draft evidence")
        if (
            self.event.event_type is not InterviewEventType.ANSWER
            and self.draft_evidence is not None
        ):
            raise ValueError("non-answer interview event cannot carry draft evidence")
        return self


class CandidateStatus(ContractModel):
    candidate_id: CandidateId
    readiness: CandidateReadinessReport
    open_gap_count: Annotated[int, Field(ge=0)]
    unconfirmed_evidence_count: Annotated[int, Field(ge=0)]
