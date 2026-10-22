# ruff: noqa: RUF001  -- Chinese messages carry full-width punctuation by design.
from datetime import UTC, datetime, timedelta

import pytest

from jobagent.conversation.service import ConversationService, is_halted_today
from jobagent.errors import ApprovalRequiredError, ContractValidationError, StaleApprovalError
from jobagent.schemas.conversation import (
    ConversationEvent,
    ConversationStage,
    DueAction,
    EventKind,
    InboundMessage,
    MessageLevel,
    ReplyDraft,
    ReplyKind,
    ReplyResult,
)
from jobagent.schemas.optimizer import VerificationReport
from jobagent.schemas.outreach import OutreachResult
from tests.harness.test_pdf import variant
from tests.outreach.test_service import approved_batch, audit

# Wednesday 2026-10-14, 10:00 in Shanghai.
NOW = datetime(2026, 10, 14, 2, 0, tzinfo=UTC)
SERVICE = ConversationService()


def opened():  # type: ignore[no-untyped-def]
    _, batch, _ = approved_batch([1])
    sent = audit(batch, 1, OutreachResult.SENT, NOW)
    conversation, event = SERVICE.open_from_outreach(sent, batch.items[0], now=NOW)
    return conversation, [event]


def inbound(
    text: str = "您好，方便发份简历吗？", level: MessageLevel = MessageLevel.L1, **flags: bool
) -> InboundMessage:
    return InboundMessage(text=text, level=level, received_at=NOW, **flags)


def receive(conversation, events, message, at=NOW):  # type: ignore[no-untyped-def]
    return events + SERVICE.receive(conversation, events, message, now=at)


def test_outreach_opens_a_greeted_conversation_bound_to_the_job() -> None:
    conversation, events = opened()

    assert conversation.job_id is not None and conversation.origin == "outreach"
    assert SERVICE.stage(events) is ConversationStage.GREETED


def test_inbound_messages_move_the_stage_by_their_flags() -> None:
    conversation, events = opened()

    replied = receive(conversation, events, inbound("您好，看了您的简历。"))
    assert SERVICE.stage(replied) is ConversationStage.REPLIED

    wants_resume = receive(conversation, replied, inbound(asks_resume=True))
    assert SERVICE.stage(wants_resume) is ConversationStage.RESUME_REQUESTED

    interview = receive(conversation, replied, inbound("明天下午面试可以吗？", MessageLevel.L3))
    assert SERVICE.stage(interview) is ConversationStage.INTERVIEW

    declined = receive(conversation, replied, inbound("不太合适哦", declined=True))
    assert SERVICE.stage(declined) is ConversationStage.DECLINED

    mismatch = receive(conversation, events, inbound("我们招证券投顾", MessageLevel.MISMATCH))
    assert SERVICE.stage(mismatch) is ConversationStage.CLOSED

    danger = receive(conversation, events, inbound("请先转账 200 元报名", MessageLevel.DANGER))
    assert SERVICE.stage(danger) is ConversationStage.GREETED


def test_stages_only_move_along_the_allowed_edges() -> None:
    conversation, events = opened()

    with pytest.raises(ContractValidationError):
        SERVICE.transition(
            conversation, events, ConversationStage.RESUME_SENT, reason="跳步", now=NOW
        )

    declined = receive(conversation, events, inbound("不合适", declined=True))
    with pytest.raises(ContractValidationError):
        SERVICE.transition(
            conversation, declined, ConversationStage.REPLIED, reason="复活", now=NOW
        )

    closed = SERVICE.transition(
        conversation, events, ConversationStage.CLOSED, reason="我方放弃", now=NOW
    )
    assert closed.stage_to is ConversationStage.CLOSED


def test_intent_is_a_person_s_answer_to_a_question_about_the_latest_message() -> None:
    conversation, events = opened()
    with pytest.raises(ContractValidationError):
        SERVICE.ask_intent(conversation, events, now=NOW)

    replied = receive(conversation, events, inbound("您好，聊聊？"))
    ask = SERVICE.ask_intent(conversation, replied, now=NOW)
    assert "聊聊" in ask.question

    newer = receive(conversation, replied, inbound("另外薪资期望是多少？", MessageLevel.L2))
    with pytest.raises(StaleApprovalError):
        SERVICE.confirm_intent(conversation, newer, ask, answer="有意向", now=NOW)
    with pytest.raises(ApprovalRequiredError):
        SERVICE.confirm_intent(conversation, replied, ask, answer=" ", now=NOW)

    event = SERVICE.confirm_intent(conversation, replied, ask, answer="有意向，推进", now=NOW)
    assert event.stage_to is ConversationStage.INTENT_CONFIRMED
    assert event.attestation == "有意向，推进"


def test_reply_drafts_follow_the_level_and_wording_rules() -> None:
    conversation, events = opened()
    follow_up = ReplyDraft(
        kind=ReplyKind.FOLLOW_UP, text="您好，想再跟进一下这个岗位，方便聊聊吗？"
    )
    assert SERVICE.draft_reply(conversation, events, follow_up, now=NOW).subject == "reply"

    replied = receive(conversation, events, inbound("您好，期望薪资多少？", MessageLevel.L2))
    last_inbound = replied[-2] if replied[-1].kind is EventKind.STAGE_CHANGED else replied[-1]
    with pytest.raises(ContractValidationError, match="follow_up_after_reply"):
        SERVICE.draft_reply(conversation, replied, follow_up, now=NOW)

    long_answer = ReplyDraft(
        kind=ReplyKind.ANSWER, text="您" * 121, in_reply_to=last_inbound.event_id
    )
    with pytest.raises(ContractValidationError, match="too_long"):
        SERVICE.draft_reply(conversation, replied, long_answer, now=NOW)

    cliche = ReplyDraft(
        kind=ReplyKind.ANSWER, text="很感兴趣，期望 22-35K。", in_reply_to=last_inbound.event_id
    )
    with pytest.raises(ContractValidationError, match="banned_phrase"):
        SERVICE.draft_reply(conversation, replied, cliche, now=NOW)

    numbers_ok = ReplyDraft(
        kind=ReplyKind.ANSWER, text="期望 22-35K，可按职级沟通。", in_reply_to=last_inbound.event_id
    )
    assert SERVICE.draft_reply(conversation, replied, numbers_ok, now=NOW).reply_digest

    resume = ReplyDraft(
        kind=ReplyKind.RESUME, text="这是我的简历，请查收。", in_reply_to=last_inbound.event_id
    )
    with pytest.raises(ContractValidationError, match="no_verified_resume"):
        SERVICE.draft_reply(conversation, replied, resume, now=NOW)

    l3 = receive(conversation, replied, inbound("加个微信吧", MessageLevel.L3))
    with pytest.raises(ContractValidationError, match="human_only"):
        SERVICE.draft_reply(conversation, l3, numbers_ok, now=NOW)


def test_l1_answers_are_capped_at_eighty_characters() -> None:
    conversation, events = opened()
    replied = receive(conversation, events, inbound("您好，什么时候能到岗？"))
    target = next(e for e in replied if e.kind is EventKind.INBOUND).event_id
    draft = ReplyDraft(kind=ReplyKind.ANSWER, text="可" * 81, in_reply_to=target)

    with pytest.raises(ContractValidationError, match="too_long"):
        SERVICE.draft_reply(conversation, replied, draft, now=NOW)


def approved_reply():  # type: ignore[no-untyped-def]
    conversation, events = opened()
    replied = receive(conversation, events, inbound("您好，什么时候能到岗？"))
    target = next(e for e in replied if e.kind is EventKind.INBOUND).event_id
    draft = ReplyDraft(kind=ReplyKind.ANSWER, text="目前已离职，随时可以到岗。", in_reply_to=target)
    ask = SERVICE.draft_reply(conversation, replied, draft, now=NOW)
    approval = SERVICE.approve_reply(conversation, replied, ask, answer="发", now=NOW)
    return conversation, [*replied, approval], ask


def test_a_reply_is_released_once_and_only_while_its_approval_is_current() -> None:
    conversation, events, ask = approved_reply()

    gate = SERVICE.reply_gate(conversation, events, lease_held=True, platform_halted=False)
    assert gate.allowed and gate.reply_digest == ask.reply_digest
    assert (
        SERVICE.reply_gate(conversation, events, lease_held=False, platform_halted=False).reason
        == "lease_not_held"
    )
    assert (
        SERVICE.reply_gate(conversation, events, lease_held=True, platform_halted=True).reason
        == "platform_halted_today"
    )

    newer = receive(conversation, events, inbound("还在吗？"))
    assert (
        SERVICE.reply_gate(conversation, newer, lease_held=True, platform_halted=False).reason
        == "stale_approval"
    )

    sent = events + SERVICE.record_reply(
        conversation, events, result=ReplyResult.SENT, reason=None, now=NOW
    )
    assert (
        SERVICE.reply_gate(conversation, sent, lease_held=True, platform_halted=False).reason
        == "nothing_approved"
    )


def test_approval_needs_the_person_s_words_and_a_current_question() -> None:
    conversation, events = opened()
    replied = receive(conversation, events, inbound("您好？"))
    target = next(e for e in replied if e.kind is EventKind.INBOUND).event_id
    ask = SERVICE.draft_reply(
        conversation,
        replied,
        ReplyDraft(kind=ReplyKind.ANSWER, text="您好，在的。", in_reply_to=target),
        now=NOW,
    )

    with pytest.raises(ApprovalRequiredError):
        SERVICE.approve_reply(conversation, replied, ask, answer="", now=NOW)
    newer = receive(conversation, replied, inbound("在吗？"))
    with pytest.raises(StaleApprovalError):
        SERVICE.approve_reply(conversation, newer, ask, answer="发", now=NOW)


def test_a_verified_resume_for_the_same_job_can_be_attached_and_sent() -> None:
    conversation, events = opened()
    replied = receive(conversation, events, inbound(asks_resume=True))
    good = variant().model_copy(update={"target_job_id": conversation.job_id})

    wrong_job = good.model_copy(update={"target_job_id": "JOB_OTHER"})
    with pytest.raises(ContractValidationError):
        SERVICE.attach_resume(conversation, replied, wrong_job, pdf_digest="sha256:pdf", now=NOW)
    unverified = good.model_copy(
        update={"verification": VerificationReport(passed=False, evidence_coverage=0)}
    )
    with pytest.raises(ContractValidationError):
        SERVICE.attach_resume(conversation, replied, unverified, pdf_digest="sha256:pdf", now=NOW)

    attached = [
        *replied,
        SERVICE.attach_resume(conversation, replied, good, pdf_digest="sha256:pdf", now=NOW),
    ]
    target = next(e for e in attached if e.kind is EventKind.INBOUND).event_id
    ask = SERVICE.draft_reply(
        conversation,
        attached,
        ReplyDraft(kind=ReplyKind.RESUME, text="这是我的简历，请查收。", in_reply_to=target),
        now=NOW,
    )
    approved = [
        *attached,
        SERVICE.approve_reply(conversation, attached, ask, answer="发简历", now=NOW),
    ]
    gate = SERVICE.reply_gate(conversation, approved, lease_held=True, platform_halted=False)
    assert gate.attachment_digest == "sha256:pdf"
    with pytest.raises(ContractValidationError, match="attachment"):
        SERVICE.record_reply(
            conversation, approved, result=ReplyResult.SENT, reason=None, now=NOW,
            attachment_digest="sha256:other",
        )
    sent = approved + SERVICE.record_reply(
        conversation, approved, result=ReplyResult.SENT, reason=None, now=NOW,
        attachment_digest="sha256:pdf",
    )

    assert SERVICE.stage(sent) is ConversationStage.RESUME_SENT


def test_due_follows_working_days_and_open_work() -> None:
    conversation, events = opened()

    friday = NOW + timedelta(days=2)
    monday = NOW + timedelta(days=5)
    assert SERVICE.due({conversation.conversation_id: (conversation, events)}, now=friday) == []
    [follow] = SERVICE.due({conversation.conversation_id: (conversation, events)}, now=monday)
    assert follow.action is DueAction.FOLLOW_UP

    follow_up_sent = _sent_follow_up(conversation, events, at=monday)
    later = monday + timedelta(days=3)
    [silent] = SERVICE.due(
        {conversation.conversation_id: (conversation, follow_up_sent)}, now=later
    )
    assert silent.action is DueAction.MARK_SILENT

    wants = receive(conversation, events, inbound(asks_resume=True))
    [tailor] = SERVICE.due({conversation.conversation_id: (conversation, wants)}, now=NOW)
    assert tailor.action is DueAction.TAILOR_RESUME

    danger = receive(conversation, events, inbound("请先转账", MessageLevel.DANGER))
    [human] = SERVICE.due({conversation.conversation_id: (conversation, danger)}, now=NOW)
    assert human.action is DueAction.HUMAN_ATTENTION


def _sent_follow_up(conversation, events, at):  # type: ignore[no-untyped-def]
    draft = ReplyDraft(kind=ReplyKind.FOLLOW_UP, text="您好，想再跟进一下，方便聊聊吗？")
    ask = SERVICE.draft_reply(conversation, events, draft, now=at)
    approved = [*events, SERVICE.approve_reply(conversation, events, ask, answer="发", now=at)]
    return approved + SERVICE.record_reply(
        conversation, approved, result=ReplyResult.SENT, reason=None, now=at
    )


def test_failures_on_a_platform_halt_it_for_the_rest_of_the_day() -> None:
    failed_reply = [("boss", NOW)]

    assert is_halted_today(
        "boss", NOW + timedelta(hours=3), outreach_audits=[], reply_failures=failed_reply
    )
    assert not is_halted_today("zhaopin", NOW, outreach_audits=[], reply_failures=failed_reply)
    assert not is_halted_today(
        "boss", NOW + timedelta(days=1), outreach_audits=[], reply_failures=failed_reply
    )


def test_events_validate_their_own_shape() -> None:
    with pytest.raises(ValueError):
        ConversationEvent(
            event_id="CEVT_X_1",
            conversation_id="CONV_X",
            seq=1,
            kind=EventKind.INBOUND,
            recorded_at=NOW,
        )


def test_a_recruiter_offering_an_excluded_role_is_closed_before_any_reply() -> None:
    conversation, event = SERVICE.open_inbound(
        platform="zhaopin",
        company="某保险公司",
        title="储备营业处经理（销售方向）",
        job_id=None,
        excluded_terms=["实习", "销售"],
        now=NOW,
    )

    assert event.stage_to is ConversationStage.CLOSED
    assert "ROLE_EXCLUSION" in (event.reason or "") and "销售" in (event.reason or "")
    with pytest.raises(ContractValidationError, match="conversation_closed"):
        SERVICE.draft_reply(
            conversation,
            [event],
            ReplyDraft(kind=ReplyKind.ANSWER, text="您好，感谢联系。"),
            now=NOW,
        )


def test_a_recruiter_offering_an_allowed_role_starts_as_replied() -> None:
    _, event = SERVICE.open_inbound(
        platform="zhaopin",
        company="某科技公司",
        title="AI 产品经理",
        job_id=None,
        excluded_terms=["销售"],
        now=NOW,
    )

    assert event.stage_to is ConversationStage.REPLIED


def test_a_conversation_the_person_started_is_logged_apart_from_outreach() -> None:
    conversation, event = SERVICE.adopt_self(
        platform="boss", company="某公司", title="AI 产品经理", job_id=None, replied=False, now=NOW
    )

    assert conversation.origin == "self"
    assert event.stage_to is ConversationStage.GREETED
    _, answered = SERVICE.adopt_self(
        platform="boss", company="某公司", title="AI 产品经理", job_id=None, replied=True, now=NOW
    )
    assert answered.stage_to is ConversationStage.REPLIED


def _answerable():  # type: ignore[no-untyped-def]
    conversation, events = opened()
    replied = receive(conversation, events, inbound("您好？"))
    target = next(e for e in replied if e.kind is EventKind.INBOUND).event_id
    return conversation, replied, target


def test_a_redraft_at_the_same_point_remembers_the_first_draft() -> None:
    conversation, replied, target = _answerable()
    first = SERVICE.draft_reply(
        conversation,
        replied,
        ReplyDraft(kind=ReplyKind.ANSWER, text="您好，在的。", in_reply_to=target),
        now=NOW,
    )
    second = SERVICE.draft_reply(
        conversation,
        replied,
        ReplyDraft(kind=ReplyKind.ANSWER, text="您好，在的，方便聊。", in_reply_to=target),
        now=NOW,
        replaces=first,
        harness_version="HVER_ABC",
    )
    third = SERVICE.draft_reply(
        conversation,
        replied,
        ReplyDraft(kind=ReplyKind.ANSWER, text="在的。", in_reply_to=target),
        now=NOW,
        replaces=second,
    )

    assert first.original_reply_digest is None
    assert second.original_reply_digest == first.reply_digest
    assert third.original_reply_digest == first.reply_digest
    assert second.harness_version == "HVER_ABC"

    approved = SERVICE.approve_reply(conversation, replied, second, answer="发", now=NOW)
    assert approved.edited_by_human is True
    assert approved.original_reply_digest == first.reply_digest
    assert approved.harness_version == "HVER_ABC"


def test_the_same_draft_asked_again_is_not_an_edit() -> None:
    conversation, replied, target = _answerable()
    draft = ReplyDraft(kind=ReplyKind.ANSWER, text="您好，在的。", in_reply_to=target)
    first = SERVICE.draft_reply(conversation, replied, draft, now=NOW)
    again = SERVICE.draft_reply(conversation, replied, draft, now=NOW, replaces=first)

    assert again.original_reply_digest is None
    approved = SERVICE.approve_reply(conversation, replied, again, answer="发", now=NOW)
    assert approved.edited_by_human is False


def test_an_earlier_question_from_another_point_is_not_a_draft_this_one_replaces() -> None:
    conversation, replied, target = _answerable()
    earlier = SERVICE.draft_reply(
        conversation,
        replied,
        ReplyDraft(kind=ReplyKind.ANSWER, text="您好，在的。", in_reply_to=target),
        now=NOW,
    )
    newer = receive(conversation, replied, inbound("在吗？"))
    latest = next(e for e in reversed(newer) if e.kind is EventKind.INBOUND).event_id
    ask = SERVICE.draft_reply(
        conversation,
        newer,
        ReplyDraft(kind=ReplyKind.ANSWER, text="在的。", in_reply_to=latest),
        now=NOW,
        replaces=earlier,
    )
    assert ask.original_reply_digest is None
