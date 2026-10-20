"""First-contact outreach: a numbered batch a person approves item by item.

Outreach is not an application: it carries no resume, only one greeting per job.
It reuses the approval discipline of applications (a question must exist before
its answer, and every answer is bound to digests of exactly what was shown), and
adds pacing: a daily cap per platform, a minimum interval, and a same-day halt
after any failure or risk-control signal. Limits can be tightened, never loosened.
"""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import ConfigDict, Field

from jobagent.schemas.applications import ApprovalChannel
from jobagent.schemas.candidate import EvidenceId
from jobagent.schemas.common import ContractModel, Digest, NonEmptyString
from jobagent.schemas.jobs import JobId

OutreachBatchId = Annotated[str, Field(pattern=r"^OBATCH_[A-Z0-9_]+$")]
OutreachAskId = Annotated[str, Field(pattern=r"^OASK_[A-Z0-9_]+$")]
OutreachApprovalId = Annotated[str, Field(pattern=r"^OAPPROVAL_[A-Z0-9_]+$")]
OutreachAuditId = Annotated[str, Field(pattern=r"^OAUDIT_[A-Z0-9_]+$")]
ItemNumber = Annotated[int, Field(ge=1)]


class OutreachPolicy(ContractModel):
    """Pacing a person approves together with the batch.

    Defaults are the ceiling. A policy may be stricter, never looser, and it is part
    of the approved digest, so changing it invalidates the approval.
    """

    daily_cap_per_platform: int = Field(default=50, ge=1, le=50)
    min_seconds_between_sends: int = Field(default=30, ge=30)
    max_items_per_batch: int = Field(default=50, ge=1, le=50)
    retry_after_failure: Literal[False] = False
    halt_platform_on_failure: Literal[True] = True


class OutreachDraft(ContractModel):
    """One first greeting a host drafted for one stored job."""

    job_id: JobId
    platform: NonEmptyString
    text: NonEmptyString
    evidence_ids: list[EvidenceId] = Field(default_factory=list)


class OutreachItem(ContractModel):
    number: ItemNumber
    job_id: JobId
    platform: NonEmptyString
    company: NonEmptyString
    title: NonEmptyString
    url: NonEmptyString
    text: NonEmptyString
    evidence_ids: list[EvidenceId] = Field(default_factory=list)
    # The job's latest match tier; None when the job was never assessed.
    match_tier: str | None = None
    # Binds the job content, the platform and the exact words to this number.
    item_digest: Digest


class OutreachBatch(ContractModel):
    batch_id: OutreachBatchId
    items: list[OutreachItem] = Field(min_length=1)
    policy: OutreachPolicy = Field(default_factory=OutreachPolicy)
    policy_digest: Digest
    batch_digest: Digest
    created_at: datetime


class OutreachRejection(ContractModel):
    index: Annotated[int, Field(ge=0)]
    job_id: str | None = None
    reasons: list[NonEmptyString] = Field(min_length=1)


class OutreachDraftReport(ContractModel):
    batch: OutreachBatch | None = None
    rejected: list[OutreachRejection] = Field(default_factory=list)


class OutreachAsk(ContractModel):
    """The numbered list put to a person. Asking approves nothing."""

    ask_id: OutreachAskId
    batch_id: OutreachBatchId
    batch_digest: Digest
    policy_digest: Digest
    question: NonEmptyString
    asked_at: datetime


class OutreachApproval(ContractModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    approval_id: OutreachApprovalId
    batch_id: OutreachBatchId
    batch_digest: Digest
    policy_digest: Digest
    approved_numbers: list[ItemNumber] = Field(min_length=1)
    approved_by: Literal["human"] = "human"
    channel: ApprovalChannel
    # The person's own words, verbatim.
    attestation: NonEmptyString
    ask_id: OutreachAskId | None = None
    approved_at: datetime


class OutreachResult(StrEnum):
    SENT = "sent"
    # The chat already held a greeting from us; nothing was sent this time.
    DUPLICATE_FOUND = "duplicate_found"
    FAILED = "failed"
    # Login, verification, risk control or a frozen page: a person must take over.
    INTERVENTION = "intervention"
    # The approved greeting will not be sent (the chat moved on, the person changed
    # their mind). Closes the item without halting the platform or counting as contact.
    WITHDRAWN = "withdrawn"


class OutreachAudit(ContractModel):
    """One row per attempt. Never updated, never deleted, never holds the text."""

    audit_id: OutreachAuditId
    batch_id: OutreachBatchId
    number: ItemNumber
    job_id: JobId
    platform: NonEmptyString
    item_digest: Digest
    approval_id: OutreachApprovalId
    approval_channel: ApprovalChannel
    result: OutreachResult
    reason: str | None = None
    recorded_at: datetime


class SendDecision(ContractModel):
    """Whether one more greeting may go out on a platform right now, and which."""

    allowed: bool
    reason: str | None = None
    item: OutreachItem | None = None
    wait_seconds: Annotated[int, Field(ge=0)] | None = None


class SiteLease(ContractModel):
    platform: NonEmptyString
    session_id: NonEmptyString
    expires_at: datetime
