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
ApprovalRequestId = Annotated[str, Field(pattern=r"^ASK_[A-Z0-9_]+$")]
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


class ApprovalChannel(StrEnum):
    """How the person's decision reached the record.

    The channel is recorded rather than asserted. On a machine where the agent
    holds the same shell the person does, no check here can prove which of them
    typed a given character, so claiming to have proved it would be a lie in an
    append-only log. What is enforced instead is the order: a relayed approval
    cannot exist unless the question it answers was posed first.
    """

    INTERACTIVE_TERMINAL = "interactive_terminal"
    AGENT_RELAY = "agent_relay"


class ApplicationPackage(ContractModel):
    application_id: ApplicationId
    job: NormalizedJob
    match: MatchResult
    resume_variant: ResumeVariant
    message: NonEmptyString
    risks: list[str] = Field(default_factory=list)
    prepared_at: datetime


class DeliveryPolicy(ContractModel):
    """The delivery rules a human approves alongside the artifacts.

    Every field is pinned by contract, so no serialization of this policy can
    describe a batch send, an approval bypass, or a retry after a platform asks
    for a human. Changing any of them changes ``policy_digest`` and therefore
    invalidates every approval minted under the old rules.
    """

    max_applications_per_request: Literal[1] = 1
    require_verified_resume_variant: Literal[True] = True
    require_matching_approval: Literal[True] = True
    retry_on_user_intervention: Literal[False] = False


class ApprovalRequest(ContractModel):
    """The question put to a person, bound to the artifacts it is about.

    Posing a question is not approving. This exists so that a relayed approval can
    be checked against something that demonstrably came first: the planner cannot
    produce a decision it never asked for.
    """

    request_id: ApprovalRequestId
    application_id: ApplicationId
    job_digest: Digest
    resume_digest: Digest
    message_digest: Digest
    policy_digest: Digest
    question: NonEmptyString
    asked_at: datetime


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
    channel: ApprovalChannel = ApprovalChannel.INTERACTIVE_TERMINAL
    # The person's own words, kept verbatim. Empty on the terminal channel, where
    # the decision was a keystroke rather than a sentence.
    attestation: str = ""
    # Which posed question this answers. Always set on the relayed channel.
    request_id: ApprovalRequestId | None = None

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
    # Which channel the approval came through, so the log states what happened
    # rather than what the older terminal-only path used to imply.
    approval_channel: ApprovalChannel | None = None
    attempt: Annotated[int, Field(ge=1)]
    result: SendResultStatus
    timestamp: datetime
    failure_reason: str | None = None
    intervention_reason: InterventionReason | None = None
