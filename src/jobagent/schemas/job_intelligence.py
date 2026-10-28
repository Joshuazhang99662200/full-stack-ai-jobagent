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
    # Carried from the listing so delivery can echo the platform's own value.
    job_kind: str | None = None
    published_at: datetime | None = None
    collected_at: datetime
    # The search the host ran when it found this posting, verbatim. It is not part of
    # the job; it is kept apart so later outcomes can be traced to the search.
    search_term: str | None = None


class JobSearchHit(ContractModel):
    """One search turning up one stored job. Only ever added, never rewritten."""

    job_id: NonEmptyString
    source: NonEmptyString
    search_term: NonEmptyString
    collected_at: datetime


class SearchRun(ContractModel):
    """One search the host ran on one board, kept even when it found nothing new."""

    source: NonEmptyString
    search_term: NonEmptyString
    searched_at: datetime
    results: int = Field(ge=0)
    new: int = Field(ge=0)


class SearchTermStat(ContractModel):
    """How one search term has done on one board so far."""

    term: NonEmptyString
    searches: int = Field(ge=0)
    results: int = Field(ge=0)
    new: int = Field(ge=0)
    hits: int = Field(ge=0)
    # Stored jobs it turned up whose latest match is strong or possible.
    promising: int = Field(ge=0)
    last_searched: datetime | None = None


class SearchPlan(ContractModel):
    source: NonEmptyString
    chosen: list[SearchTermStat]
    stats: list[SearchTermStat]


class JobListing(ContractModel):
    """A search-result row from a source that does not publish JD text.

    Deliberately distinct from ``SourceJobRecord``: a listing carries only what a
    result page exposes, so it can drive discovery and deterministic hard filters
    but can never stand in for a full job observation during tailoring.
    """

    source: NonEmptyString
    source_job_id: NonEmptyString
    title: NonEmptyString
    company: NonEmptyString
    location: str | None = None
    url: HttpUrl
    salary_text: str | None = None
    education: str | None = None
    work_years: str | None = None
    industry: str | None = None
    company_size: str | None = None
    financing_stage: str | None = None
    company_tags: list[str] = Field(default_factory=list)
    # Carried verbatim because a later step has to echo the platform's own value
    # back; upstream states it must agree with the search result it came from.
    # Never infer it and never default it — a wrong kind is worse than no kind,
    # and `None` truthfully says the search result did not carry one.
    job_kind: str | None = None
    collected_at: datetime


class JobSearchQuery(ContractModel):
    query: str = ""
    title: str | None = None
    company: str | None = None
    location: str | None = None
    source_job_id: str | None = None


class SearchTermOrigin(StrEnum):
    TARGET_ROLE = "target_role"
    TARGET_VARIANT = "target_variant"
    HEADLINE = "headline"
    RECENT_TITLE = "recent_title"
    SKILL = "skill"


class SearchQuerySuggestion(ContractModel):
    """One derived search term with the confirmed evidence that backs it."""

    term: NonEmptyString
    origin: SearchTermOrigin
    support_count: Annotated[int, Field(ge=0)]
    supporting_evidence_ids: list[EvidenceId] = Field(default_factory=list)
    query: JobSearchQuery


class SearchQuerySuggestionSet(ContractModel):
    candidate_id: CandidateId
    suggestions: list[SearchQuerySuggestion] = Field(default_factory=list)
    skipped_unconfirmed_evidence_count: Annotated[int, Field(ge=0)] = 0


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


class PreferenceFactor(ContractModel):
    """A theme the person wants more of, named by the words that signal it in a posting."""

    name: NonEmptyString
    terms: list[NonEmptyString] = Field(min_length=1)
    weight: Annotated[float, Field(gt=0)] = 1.0


class CandidateFilterContext(ContractModel):
    candidate_id: CandidateId
    allowed_locations: list[str] = Field(default_factory=list)
    remote_allowed: bool | None = None
    work_authorized_locations: list[str] = Field(default_factory=list)
    languages: dict[str, str] = Field(default_factory=dict)
    education_levels: list[str] = Field(default_factory=list)
    minimum_compensation: MoneyRange | None = None
    # Any range reaching the candidate floor qualifies; strict floor mode is opt-in.
    compensation_comparison: Literal["lower_bound", "upper_bound"] = "upper_bound"
    # A posting that states no salary ("面议") meets the floor instead of waiting
    # for review. A stated salary is still compared with the floor.
    unstated_compensation_passes: bool = False
    excluded_role_terms: list[str] = Field(default_factory=list)
    # Phrases that keep a title past an excluded term ("AI投顾" past "投顾").
    excluded_role_exceptions: list[str] = Field(default_factory=list)
    # Themes that move a posting up within its match tier, and the searches to run first.
    preferred_factors: list[PreferenceFactor] = Field(default_factory=list)
    preferred_search_terms: list[str] = Field(default_factory=list)
    # When set, a possible match gets a first greeting only at this preference or above.
    possible_match_min_preference: Annotated[float, Field(ge=0, le=1)] | None = None


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
    preference_score: Annotated[float, Field(ge=0, le=1)] = 0.0
    preference_hits: list[str] = Field(default_factory=list)


class RankedJob(ContractModel):
    job_id: JobId
    rank: Annotated[int, Field(ge=1)]
    filter_decision: FilterDecision
    match_decision: MatchDecision
    overall: Annotated[float, Field(ge=0, le=1)]
    must_have_score: Annotated[float, Field(ge=0, le=1)]
    preference_score: Annotated[float, Field(ge=0, le=1)] = 0.0
    preference_hits: list[str] = Field(default_factory=list)
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


class ImportedObservation(ContractModel):
    job_id: JobId
    source: NonEmptyString
    source_job_id: NonEmptyString
    title: NonEmptyString
    company: NonEmptyString
    # Already stored before this import, so it is not a new find.
    known_before: bool = False
    # A first greeting already reached this job; do not list it for outreach again.
    contacted: bool = False


class RejectedObservation(ContractModel):
    index: Annotated[int, Field(ge=0)]
    source_job_id: str | None = None
    # One of: invalid_record, no_host_route, url_outside_board, jd_too_short, gate_page.
    reason: NonEmptyString


class ObservationImportReport(ContractModel):
    """What a host-captured batch became. Rejections name the broken rule, never the JD."""

    stored: list[ImportedObservation] = Field(default_factory=list)
    rejected: list[RejectedObservation] = Field(default_factory=list)
