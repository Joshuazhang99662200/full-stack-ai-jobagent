"""Read-only sent-message tracking contracts; none grants sending authority."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, HttpUrl, StringConstraints, model_validator

from jobagent.schemas.candidate import CandidateId
from jobagent.schemas.common import ContractModel, Digest
from jobagent.schemas.jobs import JobId

TrackingKey = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$"
    ),
]
EvidenceReference = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=300),
]


class TrackingState(StrEnum):
    APPROVED_PENDING_EXECUTION = "approved_pending_execution"
    LEASED = "leased"
    SENT = "sent"
    AWAITING_REPLY = "awaiting_reply"
    REPLIED = "replied"
    SCREENING = "screening"
    INTERVIEW = "interview"
    REJECTED = "rejected"
    NO_RESPONSE_EXPIRED = "no_response_expired"
    JOB_CLOSED = "job_closed"
    ABANDONED_BY_USER = "abandoned_by_user"
    CLOSED = "closed"


class SentProof(ContractModel):
    send_reference: str
    job_id: JobId
    job_url: HttpUrl
    platform: str
    sent_text_hash: Digest
    sent_at: AwareDatetime
    sent_time_basis: Literal["audit_recorded_at"] = "audit_recorded_at"


class TrackingStartInput(ContractModel):
    candidate_id: CandidateId
    tracking_id: TrackingKey | None = None
    audit_id: str | None = None
    conversation_id: str | None = None
    reply_result_event_id: str | None = None
    readback_text: str = Field(min_length=1, repr=False)
    next_poll_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def source_is_exclusive(self) -> "TrackingStartInput":
        outreach = self.audit_id is not None
        conversation = self.conversation_id is not None and self.reply_result_event_id is not None
        if outreach == conversation:
            raise ValueError("Choose one existing outreach audit or approved reply result.")
        if outreach and (
            self.conversation_id is not None or self.reply_result_event_id is not None
        ):
            raise ValueError("Send proof sources cannot be mixed.")
        return self


class SentTrackingRecord(ContractModel):
    tracking_id: TrackingKey
    candidate_id: CandidateId
    job_id: JobId
    job_url: HttpUrl
    platform: str
    sent_text_hash: Digest
    sent_at: AwareDatetime
    sent_time_basis: Literal["audit_recorded_at"] = "audit_recorded_at"
    send_readback: Literal["exact"] = "exact"
    tracking_state: TrackingState
    last_checked_at: AwareDatetime | None = None
    read_at: AwareDatetime | None = None
    last_substantive_at: AwareDatetime | None = None
    registered_at: AwareDatetime | None = None
    bootstrap_next_check_at: AwareDatetime | None = None
    missed_check_days: list[int] = Field(default_factory=list)
    check_count: int = Field(default=0, ge=0)
    next_check_at: AwareDatetime | None = None
    reply_detected_at: AwareDatetime | None = None
    reply_kind: Literal["message", "screening", "interview"] | None = None
    outcome: Literal["no_response", "rejected", "screening", "interview"] | None = None
    abandoned_at: AwareDatetime | None = None
    abandon_reason: str | None = None
    tracking_version: int = Field(ge=1)
    round_number: int = Field(default=1, ge=1)
    send_references: list[str] = Field(min_length=1)
    observation_ids: list[str] = Field(default_factory=list)
    last_event_at: AwareDatetime
    paused: bool = False

    @model_validator(mode="after")
    def protect_projection(self) -> "SentTrackingRecord":
        if self.tracking_state in {
            TrackingState.APPROVED_PENDING_EXECUTION,
            TrackingState.LEASED,
        }:
            raise ValueError("Execution pre-states are projections, not sent records.")
        if (self.paused or self.tracking_state == TrackingState.CLOSED) and (
            self.next_check_at is not None
        ):
            raise ValueError("Paused or closed tracking cannot schedule a check.")
        return self


TrackingAction = Literal[
    "no_reply",
    "suspected_reply",
    "read_confirmed",
    "substantive_reply",
    "reply_confirmed",
    "screening_confirmed",
    "interview_confirmed",
    "employer_rejected",
    "job_closed",
    "user_abandon",
    "queue_closed",
    "anomaly",
    "resume",
    "reply_sent",
]


class TrackingEventInput(ContractModel):
    event_id: TrackingKey
    tracking_id: TrackingKey
    candidate_id: CandidateId
    expected_version: int = Field(ge=1)
    kind: TrackingAction
    observed_at: AwareDatetime
    observation_id: EvidenceReference
    evidence_reference: EvidenceReference
    evidence_kind: Literal[
        "conversation_message",
        "list_message",
        "unread_count",
        "detail_page",
        "list_status",
        "owner_message",
        "platform_state",
        "send_audit",
    ]
    job_url: HttpUrl | None = None
    owner_text: str | None = Field(default=None, repr=False)
    evidence_excerpt: str | None = Field(default=None, repr=False)
    conversation_id: str | None = None
    inbound_event_id: str | None = None
    reply_result_event_id: str | None = None
    readback_text: str | None = Field(default=None, repr=False)


class TrackingHistoryEvent(ContractModel):
    event_id: str
    tracking_id: TrackingKey
    version: int = Field(ge=1)
    kind: str
    occurred_at: datetime
    evidence_reference: str
    input_digest: Digest
    state: SentTrackingRecord
