"""Cumulative pipeline metrics and evidence-bound diagnosis contracts."""

from datetime import UTC, datetime
from decimal import Decimal
from itertools import pairwise
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, field_validator, model_validator

from jobagent.schemas.candidate import CandidateId
from jobagent.schemas.common import ContractModel, Digest, NonEmptyString
from jobagent.schemas.pipeline import PipelineState

Rate = Annotated[Decimal, Field(ge=0, le=1, allow_inf_nan=False)]
SalaryBand = Literal["below18k", "18-25k", "25-40k", "40k+"]
PipelineDiagnosisCode = Literal[
    "greeting_issue",
    "resume_issue",
    "funnel_blocked_at_read",
    "optimization_effective",
    "optimization_ineffective",
]
ExclusionReason = Literal[
    "job_closed",
    "employer_rejected",
    "hard_filter",
    "proof_pending",
    "direct_invite_cancelled",
    "interview_cancelled",
]
PIPELINE_FUNNEL: tuple[PipelineState, ...] = (
    "draft_pending",
    "greeting_sent",
    "greeting_read",
    "initial_contact",
    "resume_requested",
    "resume_sent",
    "interview_pending",
    "interviewed",
)
PIPELINE_FUNNEL_SEGMENTS: tuple[tuple[PipelineState, PipelineState], ...] = (
    *tuple(pairwise(PIPELINE_FUNNEL)),
    ("greeting_sent", "initial_contact"),
    ("greeting_sent", "interviewed"),
)


class PipelineSlice(ContractModel):
    dimension_platform: Literal["boss", "zhaopin", "all"]
    dimension_domain: NonEmptyString | None
    dimension_scenario: NonEmptyString | None
    dimension_tech: NonEmptyString | None
    dimension_greeting_version: NonEmptyString | None
    dimension_resume_version: NonEmptyString | None
    dimension_salary_band: SalaryBand | None


class ClosedPipelineWindow(ContractModel):
    window_start: AwareDatetime
    window_end: AwareDatetime

    @field_validator("window_start", "window_end")
    @classmethod
    def utc_timestamps(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def closed_window(self) -> "ClosedPipelineWindow":
        if self.window_end <= self.window_start:
            raise ValueError("Pipeline windows must have distinct closed UTC boundaries.")
        return self


class PipelineStageMetric(ClosedPipelineWindow, PipelineSlice):
    metric_id: NonEmptyString
    stage_from: PipelineState
    stage_to: PipelineState
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    historical_rate: Rate | None
    sliced_cumulative_rate: Rate | None
    optimized_rate: Rate | None
    window_rate: Rate | None
    sample_count: int = Field(ge=0)
    diagnosis_id: str | None

    @model_validator(mode="after")
    def consistent_cumulative_counts(self) -> "PipelineStageMetric":
        if (self.stage_from, self.stage_to) not in PIPELINE_FUNNEL_SEGMENTS:
            raise ValueError("Metrics must use an approved distinct funnel segment.")
        if self.numerator > self.denominator or self.sample_count != self.denominator:
            raise ValueError("Metric counts must be ordered and sample_count equals denominator.")
        expected = Decimal(self.numerator) / self.denominator if self.denominator else None
        if self.sliced_cumulative_rate != expected:
            raise ValueError("The cumulative rate must equal its exact cumulative counts.")
        return self


class PipelineExclusionCounts(ContractModel):
    job_closed: int = Field(ge=0)
    employer_rejected: int = Field(ge=0)
    hard_filter: int = Field(ge=0)
    proof_pending: int = Field(ge=0)
    direct_invite_cancelled: int = Field(ge=0)
    interview_cancelled: int = Field(ge=0)


class PipelineDiagnosis(ClosedPipelineWindow, PipelineSlice):
    diagnosis_id: NonEmptyString
    candidate_id: CandidateId
    metric_id: NonEmptyString
    stage_from: PipelineState
    stage_to: PipelineState
    historical_rate: Rate | None
    sliced_cumulative_rate: Rate | None
    optimized_rate: Rate | None
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    excluded_counts: PipelineExclusionCounts
    diagnosis_code: PipelineDiagnosisCode
    evidence_references: list[NonEmptyString] = Field(min_length=1)
    source_digest: Digest
    rule_id: str | None
    pre_rule_cumulative_rate: Rate | None

    @model_validator(mode="after")
    def valid_diagnosis_evidence(self) -> "PipelineDiagnosis":
        if (self.stage_from, self.stage_to) not in PIPELINE_FUNNEL_SEGMENTS:
            raise ValueError("Diagnosis must name an approved funnel segment.")
        if self.numerator > self.denominator:
            raise ValueError("Diagnosis numerator cannot exceed denominator.")
        if self.diagnosis_code.startswith("optimization_") and (
            self.optimized_rate is None
            or self.rule_id is None
            or self.pre_rule_cumulative_rate is None
        ):
            raise ValueError("Optimization review needs the exact confirmed rule and its baseline.")
        return self


class PipelineMetricFact(PipelineSlice):
    pipeline_id: NonEmptyString
    candidate_id: CandidateId
    job_id: NonEmptyString
    stage_times: dict[PipelineState, AwareDatetime]
    proof_verified: bool
    exclusion_reason: ExclusionReason | None
    evidence_references: list[NonEmptyString] = Field(min_length=1)


class ConfirmedPipelineMetricRule(ContractModel):
    rule_id: NonEmptyString
    candidate_id: CandidateId
    scope: PipelineSlice
    stage_from: PipelineState
    stage_to: PipelineState
    confirmed_at: AwareDatetime
    effective_at: AwareDatetime
    pre_rule_cumulative_rate: Rate
    owner_confirmation_reference: NonEmptyString

    @model_validator(mode="after")
    def valid_activation(self) -> "ConfirmedPipelineMetricRule":
        if self.effective_at < self.confirmed_at:
            raise ValueError("A rule cannot apply before its owner confirmation.")
        if (self.stage_from, self.stage_to) not in PIPELINE_FUNNEL_SEGMENTS:
            raise ValueError("Rule evaluation needs an approved funnel segment.")
        return self


class PipelineMetricRequest(ClosedPipelineWindow):
    candidate_id: CandidateId
    scope: PipelineSlice
    rule: ConfirmedPipelineMetricRule | None = None

    @model_validator(mode="after")
    def same_rule_scope(self) -> "PipelineMetricRequest":
        if self.rule is not None and (
            self.rule.candidate_id != self.candidate_id
            or self.rule.scope != self.scope
            or self.rule.effective_at >= self.window_end
        ):
            raise ValueError("Rule must belong to this candidate, exact slice and closed window.")
        return self


class PipelineRateCounts(ContractModel):
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)

    @model_validator(mode="after")
    def ordered_counts(self) -> "PipelineRateCounts":
        if self.numerator > self.denominator:
            raise ValueError("Rate numerator cannot exceed denominator.")
        return self


class PipelineMetricEvidence(ContractModel):
    metric_id: NonEmptyString
    candidate_id: CandidateId
    historical_counts: PipelineRateCounts
    cumulative_counts: PipelineRateCounts
    optimized_counts: PipelineRateCounts | None
    window_counts: PipelineRateCounts
    cohort_job_ids: list[str]
    excluded_counts: PipelineExclusionCounts
    exclusion_job_ids: dict[ExclusionReason, list[str]]
    evidence_references: list[NonEmptyString]
    source_digest: Digest


class PipelineMetricResult(ContractModel):
    metrics: list[PipelineStageMetric]
    evidence: list[PipelineMetricEvidence]


class PipelineDiagnosisRequest(ContractModel):
    candidate_id: CandidateId
    current: list[PipelineStageMetric] = Field(min_length=1)
    previous: list[PipelineStageMetric] = Field(default_factory=list)
    evidence: list[PipelineMetricEvidence] = Field(min_length=1)
    exclusions_reviewed: bool = False
    rule: ConfirmedPipelineMetricRule | None = None


class PipelineDiagnosisDecision(ContractModel):
    diagnoses: list[PipelineDiagnosis]
    observation_reasons: list[str]
    source_digest: Digest
