"""Whole-message proposals and independent reviews, with no approval authority."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from jobagent.schemas.candidate import CandidateId, Confidence, EvidenceId, EvidenceItem
from jobagent.schemas.common import ContractModel, Digest, NonEmptyString
from jobagent.schemas.jobs import JobId
from jobagent.schemas.outreach import OutreachDraft
from jobagent.schemas.preference_memory import PreferenceSelection


class GreetingJob(ContractModel):
    job_id: JobId
    company: NonEmptyString
    title: NonEmptyString
    platform: NonEmptyString
    url: NonEmptyString
    jd_raw: Annotated[str, Field(min_length=1, max_length=60000)]


class GreetingInterest(ContractModel):
    job: GreetingJob
    selection_id: NonEmptyString


class GreetingCorrection(ContractModel):
    older_id: EvidenceId
    replacement_id: EvidenceId
    replacement_excerpt: NonEmptyString


class GreetingSettings(ContractModel):
    candidate_id: CandidateId
    display_name: NonEmptyString
    guidance: list[NonEmptyString] = Field(default_factory=list, max_length=20)
    corrections: list[GreetingCorrection] = Field(default_factory=list, max_length=50)
    selected_job_ids: list[JobId] = Field(default_factory=list, max_length=16)
    memory_path: str | None = None


class GreetingRequest(ContractModel):
    candidate_id: CandidateId
    display_name: NonEmptyString
    mode: Literal["default", "targeted"]
    policy_digest: Digest
    job: GreetingJob | None = None
    evidence: list[EvidenceItem] = Field(min_length=1, max_length=200)
    interests: list[GreetingInterest] = Field(default_factory=list, max_length=16)
    feedback: list[NonEmptyString] = Field(default_factory=list, max_length=20)
    guidance: list[NonEmptyString] = Field(default_factory=list, max_length=20)
    corrections: list[GreetingCorrection] = Field(default_factory=list, max_length=50)
    policy_version: NonEmptyString = "whole-message.v1"
    preference_memory: PreferenceSelection | None = None
    dynamic_rules_version: Digest | None = None

    @model_validator(mode="after")
    def validate_sources(self) -> "GreetingRequest":
        if (self.mode == "targeted") != (self.job is not None):
            raise ValueError("Only targeted generation binds a stored job.")
        if self.mode == "default" and not self.interests:
            raise ValueError("Default generation requires explicit owner interest.")
        ids = {item.id for item in self.evidence}
        if len(ids) != len(self.evidence):
            raise ValueError("Evidence IDs must be unique.")
        if any(not item.user_confirmed or item.confidence is Confidence.WEAK
               for item in self.evidence):
            raise ValueError("Only confirmed admissible evidence may support a greeting.")
        by_id = {item.id: item for item in self.evidence}
        for correction in self.corrections:
            replacement = by_id.get(correction.replacement_id)
            if (correction.older_id in ids or replacement is None
                    or correction.replacement_excerpt not in replacement.statement):
                raise ValueError("Corrections need an exact current source and excluded older ID.")
        return self


class GreetingClaim(ContractModel):
    text: NonEmptyString
    evidence_ids: list[EvidenceId] = Field(min_length=1, max_length=10)


class GreetingDraft(ContractModel):
    input_digest: Digest
    text: Annotated[str, Field(min_length=1, max_length=2000)]
    angle: Annotated[str, Field(min_length=1, max_length=2000)]
    claims: list[GreetingClaim] = Field(min_length=1, max_length=12)
    jd_spans: list[NonEmptyString] = Field(default_factory=list, max_length=8)


class GreetingClaimReview(ContractModel):
    text: NonEmptyString
    verdict: Literal["supported", "partial", "unsupported", "contradicted"]
    reason: NonEmptyString


class GreetingReview(ContractModel):
    input_digest: Digest
    draft_digest: Digest
    claims: list[GreetingClaimReview] = Field(default_factory=list, max_length=12)
    full_text_supported: bool
    no_missing_claims: bool
    target_relevant: bool
    style_ok: bool
    conflicts_resolved: bool
    issues: list[NonEmptyString] = Field(default_factory=list, max_length=20)


class GreetingAttempt(ContractModel):
    draft: GreetingDraft
    review: GreetingReview | None = None
    problems: list[str] = Field(default_factory=list)


class GreetingReport(ContractModel):
    candidate_id: CandidateId
    mode: Literal["default", "targeted"]
    input_digest: Digest
    evidence_digest: Digest
    status: Literal["passed", "rejected"]
    attempts: list[GreetingAttempt] = Field(min_length=1, max_length=2)
    outreach_draft: OutreachDraft | None = None
    approval_granted: Literal[False] = False
