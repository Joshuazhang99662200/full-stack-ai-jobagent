"""Evidence-grounded resume optimization contracts."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import Field, model_validator

from jobagent.schemas.candidate import EvidenceId, MetricFact
from jobagent.schemas.common import ContractModel, Digest, NonEmptyString
from jobagent.schemas.jobs import JobId, RequirementId

ClaimId = Annotated[str, Field(pattern=r"^CLAIM_[A-Z0-9_]+$")]
ResumeItemId = Annotated[str, Field(pattern=r"^ITEM_[A-Z0-9_]+$")]
ResumeVariantId = Annotated[str, Field(pattern=r"^RESUME_[A-Z0-9_]+$")]


class VerificationStatus(StrEnum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED = "unsupported"
    CONTRADICTED = "contradicted"


class RewriteOperation(StrEnum):
    REORDER = "reorder"
    COMPRESS = "compress"
    PARAPHRASE = "paraphrase"
    TRANSLATE = "translate"
    EMPHASIZE = "emphasize"
    COMBINE = "combine"
    OMIT = "omit"


class BaseResumeItem(ContractModel):
    id: ResumeItemId
    section: NonEmptyString
    text: NonEmptyString
    evidence_ids: list[EvidenceId] = Field(default_factory=list)


class BaseResumeDocument(ContractModel):
    id: NonEmptyString
    language: NonEmptyString
    items: list[BaseResumeItem] = Field(default_factory=list)
    source_digest: Digest


class RequirementEvidenceMapping(ContractModel):
    requirement_id: RequirementId
    evidence_ids: list[EvidenceId] = Field(default_factory=list)
    relevance: Annotated[float, Field(ge=0, le=1)]
    missing_evidence: bool = False
    reason: NonEmptyString

    @model_validator(mode="after")
    def validate_missing_state(self) -> "RequirementEvidenceMapping":
        if self.missing_evidence == bool(self.evidence_ids):
            raise ValueError("missing_evidence must be true exactly when evidence_ids is empty")
        return self


class SectionOptimizationPlan(ContractModel):
    section: NonEmptyString
    objective: NonEmptyString
    source_item_ids: list[ResumeItemId] = Field(default_factory=list)
    evidence_ids: list[EvidenceId] = Field(default_factory=list)
    requirement_ids: list[RequirementId] = Field(default_factory=list)
    allowed_operations: list[RewriteOperation] = Field(default_factory=list)


class ResumeOptimizationPlan(ContractModel):
    target_job_id: JobId
    target_role: NonEmptyString
    positioning: NonEmptyString
    mappings: list[RequirementEvidenceMapping] = Field(default_factory=list)
    sections: list[SectionOptimizationPlan] = Field(default_factory=list)


class OptimizedResumeItem(ContractModel):
    id: ResumeItemId
    section: NonEmptyString
    text: NonEmptyString
    evidence_ids: list[EvidenceId] = Field(min_length=1)
    requirement_ids: list[RequirementId] = Field(default_factory=list)
    source_resume_item_ids: list[ResumeItemId] = Field(default_factory=list)
    rewrite_operations: list[RewriteOperation] = Field(default_factory=list)


class ClaimRecord(ContractModel):
    claim_id: ClaimId
    resume_item_id: ResumeItemId
    text: NonEmptyString
    claim_type: NonEmptyString
    evidence_ids: list[EvidenceId] = Field(min_length=1)
    requirement_ids: list[RequirementId] = Field(default_factory=list)
    metric_facts: list[MetricFact] = Field(default_factory=list)
    ownership_level: str | None = None
    verification_status: VerificationStatus
    verification_reasons: list[str] = Field(default_factory=list)


class ClaimLedger(ContractModel):
    claims: list[ClaimRecord] = Field(default_factory=list)


class VerificationIssue(ContractModel):
    code: NonEmptyString
    message: NonEmptyString
    claim_id: ClaimId | None = None
    resume_item_id: ResumeItemId | None = None


class VerificationReport(ContractModel):
    passed: bool
    unsupported_claims: Annotated[int, Field(ge=0)] = 0
    contradicted_claims: Annotated[int, Field(ge=0)] = 0
    unsupported_metrics: Annotated[int, Field(ge=0)] = 0
    semantic_exaggerations: Annotated[int, Field(ge=0)] = 0
    evidence_coverage: Annotated[float, Field(ge=0, le=1)]
    issues: list[VerificationIssue] = Field(default_factory=list)

    @model_validator(mode="after")
    def passing_report_requires_hard_gates(self) -> "VerificationReport":
        failures = (
            self.unsupported_claims,
            self.contradicted_claims,
            self.unsupported_metrics,
            self.semantic_exaggerations,
        )
        if self.passed and (any(failures) or self.evidence_coverage != 1.0):
            raise ValueError("a passing report must satisfy every hard quality gate")
        return self


class KeywordCoverageReport(ContractModel):
    supported_exact: list[str] = Field(default_factory=list)
    supported_synonyms: list[str] = Field(default_factory=list)
    supported_adjacent: list[str] = Field(default_factory=list)
    unsupported_missing: list[str] = Field(default_factory=list)
    stuffing_signals: list[str] = Field(default_factory=list)


class ResumeDiffItem(ContractModel):
    original: str | None = None
    optimized: str | None = None
    reason: NonEmptyString
    requirement_ids: list[RequirementId] = Field(default_factory=list)
    evidence_ids: list[EvidenceId] = Field(default_factory=list)
    rewrite_operations: list[RewriteOperation] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)


class ResumeDiff(ContractModel):
    items: list[ResumeDiffItem] = Field(default_factory=list)


class ResumeVariant(ContractModel):
    id: ResumeVariantId
    target_job_id: JobId
    target_role: NonEmptyString
    selected_evidence_ids: list[EvidenceId] = Field(default_factory=list)
    items: list[OptimizedResumeItem] = Field(default_factory=list)
    claim_ledger: ClaimLedger
    keyword_coverage: KeywordCoverageReport
    verification: VerificationReport
    diff: ResumeDiff
    prompt_bundle_digest: Digest
    generated_at: datetime


class CompatibilityBand(StrEnum):
    SAFE_REUSE = "safe_reuse"
    REVIEW = "review"
    TAILOR_SEPARATELY = "tailor_separately"


class CompatibilityThresholds(ContractModel):
    safe_reuse: Annotated[float, Field(ge=0, le=1)]
    review: Annotated[float, Field(ge=0, le=1)]

    @model_validator(mode="after")
    def validate_order(self) -> "CompatibilityThresholds":
        if self.safe_reuse <= self.review:
            raise ValueError("safe_reuse threshold must be greater than review threshold")
        return self


class ResumeCompatibilityResult(ContractModel):
    resume_variant_id: ResumeVariantId
    job_id: JobId
    candidate_job_match: Annotated[float, Field(ge=0, le=1)]
    resume_job_compatibility: Annotated[float, Field(ge=0, le=1)]
    band: CompatibilityBand
    thresholds: CompatibilityThresholds
    strengths: list[str] = Field(default_factory=list)
    missing_emphasis: list[str] = Field(default_factory=list)
