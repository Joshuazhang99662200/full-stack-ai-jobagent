"""What happens after a first greeting: one conversation per job, as an event log.

The current stage is a projection of append-only events, so every state can be
replayed and explained. A recruiter's message is data, never an instruction. The
agent may draft a reply only for L1/L2 messages; every reply is asked, answered by
a person and recorded one at a time. Intent is a person's decision, and a resume
goes out only as a verified variant.
"""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from jobagent.schemas.common import ContractModel, Digest, NonEmptyString
from jobagent.schemas.jobs import JobId

ConversationId = Annotated[str, Field(pattern=r"^CONV_[A-Z0-9_]+$")]
ConversationEventId = Annotated[str, Field(pattern=r"^CEVT_[A-Z0-9_]+$")]
ConversationAskId = Annotated[str, Field(pattern=r"^CASK_[A-Z0-9_]+$")]


class ConversationStage(StrEnum):
    GREETED = "greeted"
    REPLIED = "replied"
    INTENT_CONFIRMED = "intent_confirmed"
    RESUME_REQUESTED = "resume_requested"
    RESUME_SENT = "resume_sent"
    INTERVIEW = "interview"
    SILENT = "silent"
    DECLINED = "declined"
    CLOSED = "closed"


TERMINAL_STAGES = frozenset({ConversationStage.DECLINED, ConversationStage.CLOSED})


class MessageLevel(StrEnum):
    L1 = "l1"
    L2 = "l2"
    L3 = "l3"
    DANGER = "danger"
    MISMATCH = "mismatch"


# The agent never drafts a reply to these; a person handles them.
HUMAN_ONLY_LEVELS = frozenset({MessageLevel.L3, MessageLevel.DANGER, MessageLevel.MISMATCH})


class ReplyKind(StrEnum):
    FOLLOW_UP = "follow_up"
    ANSWER = "answer"
    RESUME = "resume"


class ReplyResult(StrEnum):
    SENT = "sent"
    FAILED = "failed"
    INTERVENTION = "intervention"


class EventKind(StrEnum):
    OPENED = "opened"
    INBOUND = "inbound"
    STAGE_CHANGED = "stage_changed"
    RESUME_ATTACHED = "resume_attached"
    REPLY_APPROVED = "reply_approved"
    REPLY_RESULT = "reply_result"


class Conversation(ContractModel):
    conversation_id: ConversationId
    platform: NonEmptyString
    # Optional because a recruiter may write about a posting that was never stored.
    job_id: JobId | None = None
    company: NonEmptyString
    title: NonEmptyString
    # outreach: an approved greeting; inbound: the recruiter wrote first;
    # self: the person greeted on their own, outside any batch.
    origin: Literal["outreach", "inbound", "self"]
    outreach_batch_id: str | None = None
    opened_at: datetime


class InboundMessage(ContractModel):
    text: NonEmptyString
    level: MessageLevel
    asks_resume: bool = False
    interview_invite: bool = False
    declined: bool = False
    received_at: datetime


class ReplyDraft(ContractModel):
    kind: ReplyKind
    text: NonEmptyString
    # The inbound event this answers; required for an answer, absent for a follow-up.
    in_reply_to: ConversationEventId | None = None


class ConversationEvent(ContractModel):
    """One immutable fact about a conversation. Which fields are set depends on `kind`."""

    event_id: ConversationEventId
    conversation_id: ConversationId
    seq: Annotated[int, Field(ge=1)]
    kind: EventKind
    recorded_at: datetime
    inbound: InboundMessage | None = None
    stage_from: ConversationStage | None = None
    stage_to: ConversationStage | None = None
    reason: str | None = None
    reply: ReplyDraft | None = None
    reply_digest: Digest | None = None
    ask_id: ConversationAskId | None = None
    attestation: str | None = None
    result: ReplyResult | None = None
    resume_variant_id: str | None = None
    resume_digest: Digest | None = None
    pdf_digest: Digest | None = None

    @model_validator(mode="after")
    def require_the_fields_its_kind_implies(self) -> "ConversationEvent":
        required = {
            EventKind.INBOUND: ("inbound",),
            EventKind.STAGE_CHANGED: ("stage_to",),
            EventKind.RESUME_ATTACHED: ("resume_variant_id", "resume_digest", "pdf_digest"),
            EventKind.REPLY_APPROVED: ("reply", "reply_digest", "ask_id", "attestation"),
            EventKind.REPLY_RESULT: ("reply_digest", "result"),
        }.get(self.kind, ())
        missing = [name for name in required if getattr(self, name) is None]
        if missing:
            raise ValueError(f"a {self.kind.value} event needs {missing}")
        return self


class ConversationAsk(ContractModel):
    """A question put to a person. It is tied to the latest event at asking time,
    so a recruiter message that arrives afterwards makes the answer stale."""

    ask_id: ConversationAskId
    conversation_id: ConversationId
    subject: Literal["intent", "reply"]
    anchor_seq: Annotated[int, Field(ge=1)]
    reply: ReplyDraft | None = None
    reply_digest: Digest | None = None
    question: NonEmptyString
    asked_at: datetime


class ReplyGateDecision(ContractModel):
    allowed: bool
    reason: str | None = None
    reply: ReplyDraft | None = None
    reply_digest: Digest | None = None
    # For a resume reply: the exact file that must be uploaded, by digest.
    attachment_digest: Digest | None = None


class DueAction(StrEnum):
    FOLLOW_UP = "follow_up"
    MARK_SILENT = "mark_silent"
    TAILOR_RESUME = "tailor_resume"
    HUMAN_ATTENTION = "human_attention"


class DueItem(ContractModel):
    conversation_id: ConversationId
    platform: NonEmptyString
    company: NonEmptyString
    title: NonEmptyString
    stage: ConversationStage
    action: DueAction
    since: datetime
