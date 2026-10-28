"""Authoritative pipeline fields; evidence and contact lineage do not duplicate state."""

import json
from typing import Literal

from pydantic import AwareDatetime, Field, HttpUrl, model_validator

from jobagent.jobs.jd_snapshot import text_digest
from jobagent.schemas.candidate import CandidateId
from jobagent.schemas.common import ContractModel, Digest, NonEmptyString

PipelineState = Literal[
    "draft_pending",
    "greeting_sent",
    "greeting_read",
    "initial_contact",
    "resume_requested",
    "resume_sent",
    "interview_pending",
    "interviewed",
    "abandoned",
]
PipelineReason = Literal[
    "normal", "read_no_reply_2d", "no_reply_2d", "employer_rejected", "job_closed", "user_abandoned"
]
PipelineEvidenceKind = Literal[
    "conversation_message",
    "list_message",
    "detail_page",
    "list_status",
    "platform_state",
    "send_audit",
    "owner_message",
    "unread_count",
]
ALLOWED_PIPELINE_TRANSITIONS: frozenset[tuple[PipelineState, PipelineState]] = frozenset(
    {
        ("draft_pending", "greeting_sent"),
        ("greeting_sent", "greeting_read"),
        ("greeting_sent", "abandoned"),
        ("greeting_read", "initial_contact"),
        ("greeting_read", "abandoned"),
        ("initial_contact", "resume_requested"),
        ("initial_contact", "interview_pending"),
        ("initial_contact", "abandoned"),
        ("resume_requested", "resume_sent"),
        ("resume_requested", "abandoned"),
        ("resume_sent", "interview_pending"),
        ("resume_sent", "abandoned"),
        ("interview_pending", "interviewed"),
        ("interview_pending", "abandoned"),
        ("interviewed", "abandoned"),
    }
)


class PipelineJob(ContractModel):
    pipeline_id: str = Field(pattern=r"^PIPE_[A-F0-9]{16}(?:_R[1-9][0-9]*)?$")
    candidate_id: CandidateId
    job_id: NonEmptyString
    platform: Literal["boss", "zhaopin"]
    job_url: HttpUrl
    title: NonEmptyString
    company: NonEmptyString
    location: str | None = None
    salary_raw: str
    salary_min_k: int | None = Field(default=None, ge=0)
    salary_max_k: int | None = Field(default=None, ge=0)
    salary_verified: Literal["pass", "fail", "review"]
    jd_text: str | None = Field(default=None, repr=False)
    jd_text_hash: Digest | None = None
    jd_points: str | None = None
    draft_greeting: str | None = Field(default=None, repr=False)
    draft_version: str | None = None
    draft_digest: Digest | None = None
    sent_greeting: str | None = Field(default=None, repr=False)
    sent_text_hash: Digest | None = None
    sent_at: AwareDatetime | None = None
    send_readback: Literal["exact", "mismatch"] | None = None
    resume_requested: bool = False
    resume_requested_at: AwareDatetime | None = None
    resume_request_evidence: str | None = None
    resume_version: str | None = None
    resume_file_id: str | None = None
    resume_sent_at: AwareDatetime | None = None
    pipeline_state: PipelineState
    state_reason: PipelineReason | None = None
    state_changed_at: AwareDatetime
    entered_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def exact_fields(self) -> "PipelineJob":
        for text, digest in [
            (self.jd_text, self.jd_text_hash),
            (self.draft_greeting, self.draft_digest),
            (self.sent_greeting, self.sent_text_hash),
        ]:
            if (text is None) != (digest is None) or (
                text is not None and text_digest(text) != digest
            ):
                raise ValueError("Exact text/hash fields must be bound together.")
        if (self.draft_greeting is None) != (self.draft_version is None):
            raise ValueError("A draft needs its actual version.")
        if self.jd_points is not None:
            points = json.loads(self.jd_points)
            if (
                not isinstance(points, list)
                or len(points) > 3
                or not all(isinstance(p, str) for p in points)
            ):
                raise ValueError("JD points must be a JSON array of at most three excerpts.")
        if self.resume_requested != (
            self.resume_requested_at is not None and self.resume_request_evidence is not None
        ):
            raise ValueError("Resume requests require confirmed evidence and time.")
        if not self.resume_requested and (self.resume_requested_at or self.resume_request_evidence):
            raise ValueError("An absent resume request cannot carry request evidence.")
        if (self.resume_version is None) != (self.resume_file_id is None):
            raise ValueError("Only a bound custom resume version/file pair is supported.")
        if self.resume_sent_at is not None and self.resume_file_id is None:
            raise ValueError("A resume send needs its custom file.")
        if self.sent_at is not None and (
            self.sent_greeting is None or self.send_readback != "exact"
        ):
            raise ValueError("A precise send needs an exact readback.")
        if not self.entered_at <= self.state_changed_at <= self.updated_at:
            raise ValueError("Pipeline times must preserve chronological order.")
        if (
            self.salary_min_k is not None
            and self.salary_max_k is not None
            and self.salary_min_k > self.salary_max_k
        ):
            raise ValueError("Salary bounds must be ordered.")
        return self


class PipelineHistory(ContractModel):
    history_id: NonEmptyString
    pipeline_id: str
    from_state: PipelineState | None
    to_state: PipelineState
    changed_at: AwareDatetime
    evidence_kind: PipelineEvidenceKind
    evidence_reference: NonEmptyString
    reason_code: PipelineReason

    @model_validator(mode="after")
    def valid_edge(self) -> "PipelineHistory":
        if self.from_state is None:
            if self.to_state != "draft_pending" or self.reason_code != "normal":
                raise ValueError("Only pipeline entry may have no previous state.")
        elif (self.from_state, self.to_state) not in ALLOWED_PIPELINE_TRANSITIONS:
            raise ValueError("Pipeline transition is not in the approved graph.")
        if self.evidence_kind == "unread_count":
            raise ValueError("Unread counts are suspected observations, not state evidence.")
        if self.to_state == "abandoned":
            if self.reason_code == "normal":
                raise ValueError("Abandonment requires a fixed reason code.")
            if self.from_state == "interviewed" and self.reason_code not in {
                "job_closed",
                "user_abandoned",
            }:
                raise ValueError("An interview cannot expire or be retroactively rejected.")
        elif self.reason_code != "normal":
            raise ValueError("Normal transitions cannot carry abandonment reasons.")
        return self


class PipelineTransition(PipelineHistory):
    history_id: str = "generated"
    event_id: NonEmptyString
    candidate_id: CandidateId
    expected_version: int = Field(ge=1)
    send_reference: str | None = None
    job_url: HttpUrl | None = None
    readback_text: str | None = Field(default=None, repr=False)
    conversation_id: str | None = None
    inbound_event_id: str | None = None
    resume_version: str | None = None
    resume_file_id: str | None = None
    attachment_digest: Digest | None = None
    owner_text: str | None = Field(default=None, repr=False)


class PipelineMeta(ContractModel):
    pipeline_id: str
    version: int = Field(default=1, ge=1)
    contact_round: int = Field(default=1, ge=1)
    normalized_job_id: str | None = None
    intake_id: str | None = None
    domain: str | None = None
    scenario: list[str] = Field(default_factory=list)
    tech: list[str] = Field(default_factory=list)
    snapshot_id: str | None = None
    feature_set_id: str | None = None
    proof_status: Literal["not_sent", "proof_pending", "verified"] = "not_sent"
    entered_time_basis: Literal["observed", "derived", "unknown_legacy"] = "observed"
    entered_evidence_reference: str
    read_at: AwareDatetime | None = None
    last_substantive_at: AwareDatetime | None = None
    last_checked_at: AwareDatetime | None = None
    abandoned_at: AwareDatetime | None = None
    last_evidence_reference: str | None = None
    sent_greeting_version: str | None = None
    paused: bool = False
    pause_reason: str | None = None


class PipelineObservation(ContractModel):
    event_id: NonEmptyString
    pipeline_id: str
    candidate_id: CandidateId
    expected_version: int = Field(ge=1)
    observed_at: AwareDatetime
    evidence_kind: PipelineEvidenceKind
    evidence_reference: NonEmptyString
    kind: Literal["no_reply", "substantive_reply", "suspected_reply", "pause", "resume"]
    conversation_id: str | None = None
    inbound_event_id: str | None = None
    owner_text: str | None = Field(default=None, repr=False)


class PipelineVerifiedEvidence(ContractModel):
    reference: str
    kind: PipelineEvidenceKind
    observed_at: AwareDatetime
    source_at: AwareDatetime
    read_confirmed: bool = False
    substantive_reply: bool = False
    asks_resume: bool = False
    interview_invite: bool = False
    interview_completed: bool = False
    employer_rejected: bool = False
    job_closed: bool = False
    owner_decision: bool = False
    sent_text: str | None = Field(default=None, repr=False)
    sent_at: AwareDatetime | None = None
    send_reference: str | None = None
    resume_version: str | None = None
    resume_file_id: str | None = None


class PipelineCreate(ContractModel):
    event_id: NonEmptyString
    candidate_id: CandidateId
    normalized_job_id: str | None = None
    intake_id: str | None = None
    evidence_reference: NonEmptyString
    domain: str | None = None
    jd_points: list[str] = Field(default_factory=list, max_length=3)
    salary_minimum_k: int = Field(ge=0)
    salary_currency: str = Field(default="CNY", min_length=3, max_length=3)
    recontact_owner_reference: str | None = None
    recontact_owner_text: str | None = Field(default=None, repr=False)
