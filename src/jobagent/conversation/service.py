"""Conversation state after a first greeting, as a pure fold over immutable events.

Every method takes the events so far and returns new events; nothing is mutated.
Recruiter text is data. The agent may draft answers to L1/L2 messages only, each
reply is approved by a person against the latest message, and a newer message
makes that approval stale before anything is sent.
"""

# ruff: noqa: RUF001  -- Questions to the person are written in Chinese.

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta

from jobagent.errors import ApprovalRequiredError, ContractValidationError, StaleApprovalError
from jobagent.jobs.hard_filter import excluded_role_term
from jobagent.outreach.rules import BANNED_PHRASES
from jobagent.outreach.service import PLATFORM_DAY
from jobagent.schemas.conversation import (
    HUMAN_ONLY_LEVELS,
    TERMINAL_STAGES,
    Conversation,
    ConversationAsk,
    ConversationEvent,
    ConversationStage,
    DueAction,
    DueItem,
    EventKind,
    InboundMessage,
    MessageLevel,
    ReplyDraft,
    ReplyGateDecision,
    ReplyKind,
    ReplyResult,
)
from jobagent.schemas.optimizer import ResumeVariant
from jobagent.schemas.outreach import OutreachAudit, OutreachItem, OutreachResult

S = ConversationStage
ALLOWED: dict[ConversationStage, frozenset[ConversationStage]] = {
    S.GREETED: frozenset(
        {S.REPLIED, S.RESUME_REQUESTED, S.INTERVIEW, S.SILENT, S.DECLINED, S.CLOSED}
    ),
    S.REPLIED: frozenset(
        {S.INTENT_CONFIRMED, S.RESUME_REQUESTED, S.INTERVIEW, S.SILENT, S.DECLINED, S.CLOSED}
    ),
    S.INTENT_CONFIRMED: frozenset(
        {S.RESUME_REQUESTED, S.RESUME_SENT, S.INTERVIEW, S.DECLINED, S.CLOSED}
    ),
    S.RESUME_REQUESTED: frozenset(
        {S.INTENT_CONFIRMED, S.RESUME_SENT, S.INTERVIEW, S.DECLINED, S.CLOSED}
    ),
    S.RESUME_SENT: frozenset({S.INTERVIEW, S.SILENT, S.DECLINED, S.CLOSED}),
    S.INTERVIEW: frozenset({S.DECLINED, S.CLOSED}),
    S.SILENT: frozenset({S.REPLIED, S.RESUME_REQUESTED, S.INTERVIEW, S.DECLINED, S.CLOSED}),
    S.DECLINED: frozenset(),
    S.CLOSED: frozenset(),
}

MAX_REPLY_CHARS = 120
MAX_L1_REPLY_CHARS = 80
FOLLOW_UP_AFTER_WORKDAYS = 2
SILENT_AFTER_DAYS = 3
_HALTING_OUTREACH = frozenset({OutreachResult.FAILED, OutreachResult.INTERVENTION})


def _digest(value: object) -> str:
    canonical = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def conversation_id_for(platform: str, key: str) -> str:
    return f"CONV_{hashlib.sha256(f'{platform}|{key}'.encode()).hexdigest()[:16].upper()}"


def _local(moment: datetime) -> date:
    return moment.astimezone(PLATFORM_DAY).date()


def workdays_between(start: datetime, end: datetime) -> int:
    """Weekdays strictly after `start`'s day and strictly before `end`'s day."""
    first, last = _local(start), _local(end)
    days = 0
    current = first + timedelta(days=1)
    while current < last:
        days += current.weekday() < 5
        current += timedelta(days=1)
    return days


def is_halted_today(
    platform: str,
    now: datetime,
    *,
    outreach_audits: Sequence[OutreachAudit],
    reply_failures: Sequence[tuple[str, datetime]],
) -> bool:
    """A failure or risk-control signal from any send halts the platform for the day."""
    today = _local(now)
    if any(
        audit.platform == platform
        and audit.result in _HALTING_OUTREACH
        and _local(audit.recorded_at) == today
        for audit in outreach_audits
    ):
        return True
    return any(name == platform and _local(at) == today for name, at in reply_failures)


UNKNOWN_TITLES = frozenset({"", "未注明", "未知", "-"})


def company_key(company: str) -> str:
    """The company with bracketed notes, recruiter names and the word 猎头 removed.

    Boards write the same recruiter several ways ("猎头(某公司)", "某公司(猎头)" in
    full-width brackets, "某公司(王女士)"); conversations are matched on this key
    so one recruiter is logged once.
    """
    brackets = r"[(（]([^()（）]*)[)）]"
    outside = re.sub(brackets, "", company).replace("猎头", "")
    if not re.sub(r"\s+", "", outside):
        # "猎头(某公司)": the company itself sits in the brackets.
        outside = " ".join(re.findall(brackets, company)).replace("猎头", "")
    return re.sub(r"\s+", "", outside).casefold()


def screened_term(
    title: str, company: str, excluded_terms: Sequence[str], exceptions: Sequence[str] = ()
) -> str | None:
    """An excluded role term found in the title or the company name."""
    return excluded_role_term(f"{title} {company}", excluded_terms, exceptions)


class ConversationService:
    # -- opening -----------------------------------------------------------------

    def open_from_outreach(
        self, audit: OutreachAudit, item: OutreachItem, *, now: datetime
    ) -> tuple[Conversation, ConversationEvent]:
        conversation = Conversation(
            conversation_id=conversation_id_for(item.platform, item.job_id),
            platform=item.platform,
            job_id=item.job_id,
            company=item.company,
            title=item.title,
            origin="outreach",
            outreach_batch_id=audit.batch_id,
            opened_at=audit.recorded_at,
        )
        return conversation, self._event(
            conversation,
            [],
            EventKind.OPENED,
            now=audit.recorded_at,
            stage_to=S.GREETED,
            reason=f"outreach {audit.batch_id}#{audit.number}",
        )

    def open_inbound(
        self,
        *,
        platform: str,
        company: str,
        title: str,
        job_id: str | None,
        excluded_terms: Sequence[str],
        now: datetime,
        exceptions: Sequence[str] = (),
    ) -> tuple[Conversation, ConversationEvent]:
        """A recruiter wrote first. The conversation starts as already replied.

        A recruiter reaching out is screened like a posting found by search: a title
        that names one of the person's excluded roles closes the conversation at once,
        so no reply can be drafted for it.
        """
        excluded = screened_term(title, company, excluded_terms, exceptions)
        key = job_id or f"{company}|{title}"
        conversation = Conversation(
            conversation_id=conversation_id_for(platform, key),
            platform=platform,
            job_id=job_id,
            company=company,
            title=title,
            origin="inbound",
            opened_at=now,
        )
        return conversation, self._event(
            conversation,
            [],
            EventKind.OPENED,
            now=now,
            stage_to=S.REPLIED if excluded is None else S.CLOSED,
            reason="recruiter wrote first"
            if excluded is None
            else f"recruiter wrote first; ROLE_EXCLUSION: {excluded}",
        )

    def adopt_self(
        self,
        *,
        platform: str,
        company: str,
        title: str,
        job_id: str | None,
        replied: bool,
        now: datetime,
    ) -> tuple[Conversation, ConversationEvent]:
        """The person greeted on their own. Kept apart from outreach, followed up the same way."""
        key = job_id or f"{company}|{title}"
        conversation = Conversation(
            conversation_id=conversation_id_for(platform, key),
            platform=platform,
            job_id=job_id,
            company=company,
            title=title,
            origin="self",
            opened_at=now,
        )
        return conversation, self._event(
            conversation,
            [],
            EventKind.OPENED,
            now=now,
            stage_to=S.REPLIED if replied else S.GREETED,
            reason="the person greeted on their own",
        )

    # -- state -------------------------------------------------------------------

    @staticmethod
    def stage(events: Sequence[ConversationEvent]) -> ConversationStage | None:
        current: ConversationStage | None = None
        for event in events:
            if event.stage_to is not None:
                current = event.stage_to
        return current

    def receive(
        self,
        conversation: Conversation,
        events: Sequence[ConversationEvent],
        message: InboundMessage,
        *,
        now: datetime,
    ) -> list[ConversationEvent]:
        """Record a recruiter's message and the stage change its flags imply."""
        current = self._require_open(conversation, events)
        recorded = self._event(conversation, events, EventKind.INBOUND, now=now, inbound=message)
        target = self._stage_for(current, message)
        if target is None or target == current:
            return [recorded]
        change = self._event(
            conversation,
            [*events, recorded],
            EventKind.STAGE_CHANGED,
            now=now,
            stage_from=current,
            stage_to=target,
            reason=f"inbound {message.level.value}",
        )
        return [recorded, change]

    @staticmethod
    def _stage_for(current: ConversationStage, message: InboundMessage) -> ConversationStage | None:
        if message.declined:
            return S.DECLINED
        if message.level is MessageLevel.MISMATCH:
            return S.CLOSED
        if message.level is MessageLevel.DANGER:
            return None
        if message.interview_invite or message.level is MessageLevel.L3:
            return S.INTERVIEW if S.INTERVIEW in ALLOWED[current] else None
        if message.asks_resume and S.RESUME_REQUESTED in ALLOWED[current]:
            return S.RESUME_REQUESTED
        if current in (S.GREETED, S.SILENT):
            return S.REPLIED
        return None

    def transition(
        self,
        conversation: Conversation,
        events: Sequence[ConversationEvent],
        target: ConversationStage,
        *,
        reason: str,
        now: datetime,
    ) -> ConversationEvent:
        current = self._require_open(conversation, events)
        if target not in ALLOWED[current]:
            raise ContractValidationError(
                "That stage cannot follow the current one.",
                details={
                    "conversation_id": conversation.conversation_id,
                    "from": current.value,
                    "to": target.value,
                },
            )
        if not reason.strip():
            raise ContractValidationError("A stage change needs a reason.")
        return self._event(
            conversation,
            events,
            EventKind.STAGE_CHANGED,
            now=now,
            stage_from=current,
            stage_to=target,
            reason=reason.strip(),
        )

    # -- intent ------------------------------------------------------------------

    def ask_intent(
        self, conversation: Conversation, events: Sequence[ConversationEvent], *, now: datetime
    ) -> ConversationAsk:
        self._require_open(conversation, events)
        last = self._latest_inbound(events)
        if last is None or last.inbound is None:
            raise ContractValidationError(
                "Intent can only be confirmed after the recruiter has written.",
                details={"conversation_id": conversation.conversation_id},
            )
        question = (
            f"{conversation.platform}｜{conversation.company}｜{conversation.title}\n"
            f"对方最新消息：{last.inbound.text}\n是否确认对这个岗位有意向、开始做定向简历？"
        )
        return ConversationAsk(
            ask_id=self._ask_id(conversation, events, "I"),
            conversation_id=conversation.conversation_id,
            subject="intent",
            anchor_seq=events[-1].seq,
            question=question,
            asked_at=now,
        )

    def confirm_intent(
        self,
        conversation: Conversation,
        events: Sequence[ConversationEvent],
        ask: ConversationAsk,
        *,
        answer: str,
        now: datetime,
    ) -> ConversationEvent:
        self._check_answer(conversation, events, ask, answer, subject="intent")
        current = self._require_open(conversation, events)
        if S.INTENT_CONFIRMED not in ALLOWED[current]:
            raise ContractValidationError(
                "Intent cannot be confirmed from this stage.",
                details={"conversation_id": conversation.conversation_id, "stage": current.value},
            )
        return self._event(
            conversation,
            events,
            EventKind.STAGE_CHANGED,
            now=now,
            stage_from=current,
            stage_to=S.INTENT_CONFIRMED,
            reason="person confirmed intent",
            ask_id=ask.ask_id,
            attestation=answer.strip(),
        )

    # -- replies -----------------------------------------------------------------

    def draft_reply(
        self,
        conversation: Conversation,
        events: Sequence[ConversationEvent],
        draft: ReplyDraft,
        *,
        now: datetime,
    ) -> ConversationAsk:
        """Check a host-drafted reply and turn it into a question for the person."""
        problems = self._reply_problems(conversation, events, draft)
        if problems:
            raise ContractValidationError(
                "The reply breaks the conversation rules: " + ", ".join(problems),
                details={"conversation_id": conversation.conversation_id, "problems": problems},
            )
        last = self._latest_inbound(events)
        heard = f"对方最新消息：{last.inbound.text}\n" if last is not None and last.inbound else ""
        reply_digest = _digest(
            {"conversation": conversation.conversation_id, **draft.model_dump(mode="json")}
        )
        return ConversationAsk(
            ask_id=self._ask_id(conversation, events, "R"),
            conversation_id=conversation.conversation_id,
            subject="reply",
            anchor_seq=events[-1].seq,
            reply=draft,
            reply_digest=reply_digest,
            question=(
                f"{conversation.platform}｜{conversation.company}｜{conversation.title}\n"
                f"{heard}拟回复（{draft.kind.value}）：{draft.text}\n回复“发”即同意发送这一条。"
            ),
            asked_at=now,
        )

    def _reply_problems(
        self, conversation: Conversation, events: Sequence[ConversationEvent], draft: ReplyDraft
    ) -> list[str]:
        current = self.stage(events)
        if current is None or current in TERMINAL_STAGES:
            return ["conversation_closed"]
        last = self._latest_inbound(events)
        problems: list[str] = []
        if draft.kind is ReplyKind.FOLLOW_UP:
            if last is not None:
                problems.append("follow_up_after_reply")
        else:
            if last is None or last.inbound is None:
                return ["nothing_to_answer"]
            if last.inbound.level in HUMAN_ONLY_LEVELS:
                return ["human_only"]
            if draft.in_reply_to != last.event_id:
                problems.append("not_the_latest_message")
        limit = (
            MAX_L1_REPLY_CHARS
            if last is not None
            and last.inbound is not None
            and last.inbound.level is MessageLevel.L1
            and draft.kind is ReplyKind.ANSWER
            else MAX_REPLY_CHARS
        )
        if len("".join(draft.text.split())) > limit:
            problems.append("too_long")
        folded = draft.text.casefold()
        problems.extend(
            f"banned_phrase:{phrase}" for phrase in BANNED_PHRASES if phrase.casefold() in folded
        )
        if draft.kind is ReplyKind.RESUME and self._attached_resume(events) is None:
            problems.append("no_verified_resume")
        return problems

    def approve_reply(
        self,
        conversation: Conversation,
        events: Sequence[ConversationEvent],
        ask: ConversationAsk,
        *,
        answer: str,
        now: datetime,
    ) -> ConversationEvent:
        self._check_answer(conversation, events, ask, answer, subject="reply")
        assert ask.reply is not None and ask.reply_digest is not None
        return self._event(
            conversation,
            events,
            EventKind.REPLY_APPROVED,
            now=now,
            reply=ask.reply,
            reply_digest=ask.reply_digest,
            ask_id=ask.ask_id,
            attestation=answer.strip(),
        )

    def reply_gate(
        self,
        conversation: Conversation,
        events: Sequence[ConversationEvent],
        *,
        lease_held: bool,
        platform_halted: bool,
    ) -> ReplyGateDecision:
        """Decide whether the approved reply may be sent now."""
        approval = self._pending_approval(events)
        if approval is None:
            return ReplyGateDecision(allowed=False, reason="nothing_approved")
        if any(e.kind is EventKind.INBOUND and e.seq > approval.seq for e in events):
            return ReplyGateDecision(allowed=False, reason="stale_approval")
        if not lease_held:
            return ReplyGateDecision(allowed=False, reason="lease_not_held")
        if platform_halted:
            return ReplyGateDecision(allowed=False, reason="platform_halted_today")
        attached = self._attached_resume(events)
        attachment = (
            attached.pdf_digest
            if approval.reply is not None
            and approval.reply.kind is ReplyKind.RESUME
            and attached is not None
            else None
        )
        return ReplyGateDecision(
            allowed=True,
            reply=approval.reply,
            reply_digest=approval.reply_digest,
            attachment_digest=attachment,
        )

    def record_reply(
        self,
        conversation: Conversation,
        events: Sequence[ConversationEvent],
        *,
        result: ReplyResult,
        reason: str | None,
        now: datetime,
        attachment_digest: str | None = None,
    ) -> list[ConversationEvent]:
        """Record what happened. A sent resume must be the exact attached file."""
        approval = self._pending_approval(events)
        if approval is None or approval.reply is None:
            raise ApprovalRequiredError(
                "There is no approved reply waiting to be recorded.",
                details={"conversation_id": conversation.conversation_id},
            )
        if result is ReplyResult.SENT and approval.reply.kind is ReplyKind.RESUME:
            attached = self._attached_resume(events)
            if attached is None or attachment_digest != attached.pdf_digest:
                raise ContractValidationError(
                    "The uploaded file is not the attached, verified resume (attachment).",
                    details={"conversation_id": conversation.conversation_id},
                )
        recorded = self._event(
            conversation,
            events,
            EventKind.REPLY_RESULT,
            now=now,
            reply_digest=approval.reply_digest,
            result=result,
            reason=reason,
        )
        if result is ReplyResult.SENT and approval.reply.kind is ReplyKind.RESUME:
            current = self.stage(events)
            if current is not None and S.RESUME_SENT in ALLOWED[current]:
                return [
                    recorded,
                    self._event(
                        conversation,
                        [*events, recorded],
                        EventKind.STAGE_CHANGED,
                        now=now,
                        stage_from=current,
                        stage_to=S.RESUME_SENT,
                        reason="resume sent",
                    ),
                ]
        return [recorded]

    # -- resume ------------------------------------------------------------------

    def attach_resume(
        self,
        conversation: Conversation,
        events: Sequence[ConversationEvent],
        variant: ResumeVariant,
        *,
        pdf_digest: str,
        now: datetime,
    ) -> ConversationEvent:
        self._require_open(conversation, events)
        if conversation.job_id is None or variant.target_job_id != conversation.job_id:
            raise ContractValidationError(
                "The resume was tailored for a different job.",
                details={"conversation_id": conversation.conversation_id},
            )
        if not variant.verification.passed:
            raise ContractValidationError(
                "Only a verified resume variant can be attached.",
                details={"conversation_id": conversation.conversation_id, "variant": variant.id},
            )
        return self._event(
            conversation,
            events,
            EventKind.RESUME_ATTACHED,
            now=now,
            resume_variant_id=variant.id,
            resume_digest=_digest(variant.model_dump(mode="json", exclude={"generated_at"})),
            pdf_digest=pdf_digest,
        )

    # -- due ---------------------------------------------------------------------

    def due(
        self,
        conversations: Mapping[str, tuple[Conversation, Sequence[ConversationEvent]]],
        *,
        now: datetime,
    ) -> list[DueItem]:
        items: list[DueItem] = []
        for conversation, events in conversations.values():
            current = self.stage(events)
            if current is None or current in TERMINAL_STAGES or not events:
                continue
            action, since = self._due_action(current, events, now)
            if action is not None and since is not None:
                items.append(
                    DueItem(
                        conversation_id=conversation.conversation_id,
                        platform=conversation.platform,
                        company=conversation.company,
                        title=conversation.title,
                        stage=current,
                        action=action,
                        since=since,
                    )
                )
        return sorted(items, key=lambda item: (item.action.value, item.since))

    def _due_action(
        self, current: ConversationStage, events: Sequence[ConversationEvent], now: datetime
    ) -> tuple[DueAction | None, datetime | None]:
        last_inbound = self._latest_inbound(events)
        if last_inbound is not None and last_inbound.inbound is not None:
            answered = any(
                e.kind is EventKind.REPLY_RESULT and e.seq > last_inbound.seq for e in events
            )
            if (
                last_inbound.inbound.level in (MessageLevel.DANGER, MessageLevel.L3)
                and not answered
            ):
                return DueAction.HUMAN_ATTENTION, last_inbound.recorded_at
        if (
            current in (S.INTENT_CONFIRMED, S.RESUME_REQUESTED)
            and self._attached_resume(events) is None
        ):
            return DueAction.TAILOR_RESUME, events[-1].recorded_at
        if current is S.GREETED and last_inbound is None:
            follow_ups = [
                e
                for e in events
                if e.kind is EventKind.REPLY_RESULT and e.result is ReplyResult.SENT
            ]
            if follow_ups:
                sent_at = follow_ups[-1].recorded_at
                if (now - sent_at) >= timedelta(days=SILENT_AFTER_DAYS):
                    return DueAction.MARK_SILENT, sent_at
                return None, None
            greeted_at = events[0].recorded_at
            if workdays_between(greeted_at, now) >= FOLLOW_UP_AFTER_WORKDAYS:
                return DueAction.FOLLOW_UP, greeted_at
        return None, None

    # -- helpers -----------------------------------------------------------------

    def _require_open(
        self, conversation: Conversation, events: Sequence[ConversationEvent]
    ) -> ConversationStage:
        current = self.stage(events)
        if current is None or current in TERMINAL_STAGES:
            raise ContractValidationError(
                "This conversation is closed.",
                details={"conversation_id": conversation.conversation_id},
            )
        return current

    @staticmethod
    def _latest_inbound(events: Sequence[ConversationEvent]) -> ConversationEvent | None:
        return next((e for e in reversed(events) if e.kind is EventKind.INBOUND), None)

    @staticmethod
    def _attached_resume(events: Sequence[ConversationEvent]) -> ConversationEvent | None:
        return next((e for e in reversed(events) if e.kind is EventKind.RESUME_ATTACHED), None)

    @staticmethod
    def _pending_approval(events: Sequence[ConversationEvent]) -> ConversationEvent | None:
        approval = next((e for e in reversed(events) if e.kind is EventKind.REPLY_APPROVED), None)
        if approval is None:
            return None
        done = any(
            e.kind is EventKind.REPLY_RESULT
            and e.reply_digest == approval.reply_digest
            and e.seq > approval.seq
            for e in events
        )
        return None if done else approval

    def _check_answer(
        self,
        conversation: Conversation,
        events: Sequence[ConversationEvent],
        ask: ConversationAsk,
        answer: str,
        *,
        subject: str,
    ) -> None:
        details = {"conversation_id": conversation.conversation_id, "ask_id": ask.ask_id}
        if ask.conversation_id != conversation.conversation_id or ask.subject != subject:
            raise ApprovalRequiredError("The question was about something else.", details=details)
        if not answer.strip():
            raise ApprovalRequiredError(
                "The approval must carry the person's own answer.", details=details
            )
        if events and events[-1].seq != ask.anchor_seq:
            raise StaleApprovalError(
                "The conversation moved on after the question was asked.", details=details
            )

    @staticmethod
    def _ask_id(conversation: Conversation, events: Sequence[ConversationEvent], tag: str) -> str:
        suffix = conversation.conversation_id.removeprefix("CONV_")
        return f"CASK_{suffix}_{tag}{events[-1].seq if events else 0}"

    @staticmethod
    def _event(
        conversation: Conversation,
        events: Sequence[ConversationEvent],
        kind: EventKind,
        *,
        now: datetime,
        **fields: object,
    ) -> ConversationEvent:
        seq = (events[-1].seq if events else 0) + 1
        suffix = conversation.conversation_id.removeprefix("CONV_")
        return ConversationEvent(
            event_id=f"CEVT_{suffix}_{seq}",
            conversation_id=conversation.conversation_id,
            seq=seq,
            kind=kind,
            recorded_at=now,
            **fields,  # type: ignore[arg-type]
        )
