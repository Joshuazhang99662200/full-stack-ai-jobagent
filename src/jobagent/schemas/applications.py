"""Human review, digest-bound approval, delivery, batch, and audit contracts."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import ConfigDict, Field

from jobagent.schemas.common import ContractModel, Digest, NonEmptyString
from jobagent.schemas.jobs import MatchResult, NormalizedJob
from jobagent.schemas.optimizer import ResumeVariant

ApplicationId = Annotated[str, Field(pattern=r"^APP_[A-Z0-9_]+$")]
ApprovalId = Annotated[str, Field(pattern=r"^APPROVAL_[A-Z0-9_]+$")]
BatchId = Annotated[str, Field(pattern=r"^BATCH_[A-Z0-9_]+$")]
AuditId = Annotated[str, Field(pattern=r"^AUDIT_[A-Z0-9_]+$")]


class ApplicationStatus(StrEnum):
    PREPARED = "prepared"
    PREVIEWED = "previewed"
    APPROVED = "approved"
    SENT = "sent"
    FAILED = "failed"
    INTERVENTION_REQUIRED = "intervention_required"


class InterventionReason(StrEnum):
    LOGIN_REQUIRED = "login_required"
    CAPTCHA_REQUIRED = "captcha_required"
    VERIFICATION_REQUIRED = "verification_required"
    RISK_CONTROL = "risk_control"
    PLATFORM_CHANGED = "platform_changed"


class SendResultStatus(StrEnum):
    SENT = "sent"
    FAILED = "failed"
    USER_INTERVENTION_REQUIRED = "user_intervention_required"


class ApplicationPackage(ContractModel):
    application_id: ApplicationId
    job: NormalizedJob
    match: MatchResult
    resume_variant: ResumeVariant
    message: NonEmptyString
    risks: list[str] = Field(default_factory=list)
    prepared_at: datetime


class ApprovalRecord(ContractModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    approval_id: ApprovalId | None = None
    application_id: ApplicationId
    job_digest: Digest
    resume_digest: Digest
    message_digest: Digest
    policy_digest: Digest
    approved_at: datetime
    approved_by: Literal["human"]

    def matches(
        self,
        *,
        job_digest: str,
        resume_digest: str,
        message_digest: str,
        policy_digest: str,
    ) -> bool:
        return (
            self.job_digest == job_digest
            and self.resume_digest == resume_digest
            and self.message_digest == message_digest
            and self.policy_digest == policy_digest
        )


class DeliveryRequest(ContractModel):
    application_id: ApplicationId
    approval: ApprovalRecord
    job_digest: Digest
    resume_digest: Digest
    message_digest: Digest
    policy_digest: Digest


class DeliveryResult(ContractModel):
    application_id: ApplicationId
    status: SendResultStatus
    attempted_at: datetime
    external_reference: str | None = None
    failure_reason: str | None = None
    intervention_reason: InterventionReason | None = None


class BatchExecutionMode(StrEnum):
    SEQUENTIAL = "sequential"


class BatchApplication(ContractModel):
    batch_id: BatchId
    application_ids: list[ApplicationId] = Field(min_length=1)
    execution_mode: BatchExecutionMode = BatchExecutionMode.SEQUENTIAL
    approval_records: list[ApprovalRecord] = Field(default_factory=list)


class ApplicationAudit(ContractModel):
    audit_id: AuditId
    application_id: ApplicationId
    job_id: NonEmptyString
    platform: NonEmptyString
    resume_variant_id: NonEmptyString
    resume_digest: Digest
    message_digest: Digest
    approval_id: ApprovalId | None = None
    attempt: Annotated[int, Field(ge=1)]
    result: SendResultStatus
    timestamp: datetime
    failure_reason: str | None = None
    intervention_reason: InterventionReason | None = None
