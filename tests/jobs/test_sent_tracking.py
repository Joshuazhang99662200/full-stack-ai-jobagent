# ruff: noqa: RUF001 -- Synthetic Chinese message punctuation.
from datetime import UTC, datetime, timedelta

import pytest

from jobagent.errors import ContractValidationError

NOW = datetime(2026, 10, 28, 2, tzinfo=UTC)
TEXT = "您好，这是一条合成测试招呼，方便交流吗？"


def outreach_records():
    from jobagent.jobs.jd_snapshot import canonical_digest
    from jobagent.outreach.service import policy_digest
    from jobagent.schemas.applications import ApprovalChannel
    from jobagent.schemas.outreach import (
        OutreachApproval,
        OutreachAudit,
        OutreachBatch,
        OutreachItem,
        OutreachPolicy,
        OutreachResult,
    )

    policy = OutreachPolicy()
    item = OutreachItem(
        number=1,
        job_id="JOB_DEMO_1",
        platform="boss",
        company="合成公司",
        title="合成岗位",
        url="https://example.com/synthetic/1",
        text=TEXT,
        item_digest="sha256:synthetic-item",
    )
    batch = OutreachBatch(
        batch_id="OBATCH_DEMO",
        items=[item],
        policy=policy,
        policy_digest=policy_digest(policy),
        batch_digest=canonical_digest([[1, item.item_digest]]),
        created_at=NOW,
    )
    approval = OutreachApproval(
        approval_id="OAPPROVAL_DEMO",
        batch_id=batch.batch_id,
        batch_digest=batch.batch_digest,
        policy_digest=batch.policy_digest,
        approved_numbers=[1],
        attestation="确认发送这条合成文本",
        channel=ApprovalChannel.AGENT_RELAY,
        ask_id="OASK_DEMO",
        approved_at=NOW,
    )
    audit = OutreachAudit(
        audit_id="OAUDIT_DEMO",
        batch_id=batch.batch_id,
        number=1,
        job_id=item.job_id,
        platform=item.platform,
        item_digest=item.item_digest,
        approval_id=approval.approval_id,
        approval_channel=approval.channel,
        result=OutreachResult.SENT,
        recorded_at=NOW,
    )
    return batch, approval, audit


def proof():
    from jobagent.jobs.sent_tracking import outreach_proof

    return outreach_proof(*outreach_records(), TEXT)


def record():
    from jobagent.jobs.sent_tracking import start_tracking

    return start_tracking(proof(), candidate_id="CAND_DEMO", tracking_id="TRACK_DEMO", now=NOW)[
        -1
    ].state


def event(value, kind, day=1, **changes):
    from jobagent.schemas.sent_tracking import TrackingEventInput

    data = {
        "event_id": f"EV_{value.tracking_version}_{kind}",
        "tracking_id": value.tracking_id,
        "candidate_id": value.candidate_id,
        "expected_version": value.tracking_version,
        "kind": kind,
        "observed_at": NOW + timedelta(days=day),
        "observation_id": f"OBS_{value.tracking_version}_{kind}",
        "evidence_reference": f"READ_{value.tracking_version}_{kind}",
        "evidence_kind": "conversation_message",
    }
    data.update(changes)
    return TrackingEventInput.model_validate(data)


def apply(value, kind, day=1, conversation=None, inbound=None, reply_proof=None, **changes):
    from jobagent.jobs.sent_tracking import advance

    update = event(value, kind, day, **changes)
    events = advance(
        value,
        update,
        now=update.observed_at,
        conversation=conversation,
        inbound=inbound,
        reply_proof=reply_proof,
    )
    return events[-1].state, events


def inbound_evidence(number=1, **changes):
    from jobagent.schemas.conversation import (
        Conversation,
        ConversationEvent,
        EventKind,
        InboundMessage,
        MessageLevel,
    )

    conversation = Conversation(
        conversation_id="CONV_DEMO",
        platform="boss",
        job_id="JOB_DEMO_1",
        company="合成公司",
        title="合成岗位",
        origin="outreach",
        outreach_batch_id="OBATCH_DEMO",
        opened_at=NOW,
    )
    data = {
        "text": "合成招聘方消息：请提供简历，进入下一步初筛。",
        "level": MessageLevel.L2,
        "asks_resume": True,
        "received_at": NOW + timedelta(days=1),
    }
    data.update(changes)
    inbound = ConversationEvent(
        event_id=f"CEVT_IN_{number}",
        conversation_id=conversation.conversation_id,
        seq=number + 1,
        kind=EventKind.INBOUND,
        recorded_at=NOW + timedelta(days=1),
        inbound=InboundMessage.model_validate(data),
    )
    return conversation, inbound


def confirm(value, kind="reply_confirmed", day=1, **inbound_changes):
    conversation, inbound = inbound_evidence(**inbound_changes)
    return apply(
        value,
        kind,
        day,
        conversation=conversation,
        inbound=inbound,
        conversation_id=conversation.conversation_id,
        inbound_event_id=inbound.event_id,
        evidence_reference=inbound.event_id,
    )


def test_tracking_creation_needs_approved_sent_audit_and_exact_text():
    from jobagent.jobs.sent_tracking import outreach_proof
    from jobagent.schemas.outreach import OutreachResult

    batch, approval, audit = outreach_records()
    assert proof().sent_text_hash
    for altered, text in [
        (audit, TEXT + " "),
        (audit.model_copy(update={"result": OutreachResult.FAILED}), TEXT),
        (audit.model_copy(update={"approval_id": "OAPPROVAL_OTHER"}), TEXT),
        (audit.model_copy(update={"job_id": "JOB_OTHER"}), TEXT),
    ]:
        with pytest.raises(ContractValidationError):
            outreach_proof(batch, approval, altered, text)


def test_sent_and_awaiting_are_both_preserved_and_first_check_is_day_one():
    from jobagent.jobs.sent_tracking import start_tracking

    history = start_tracking(proof(), candidate_id="CAND_DEMO", tracking_id="TRACK_DEMO", now=NOW)
    assert [e.state.tracking_state.value for e in history] == ["sent", "awaiting_reply"]
    assert history[-1].state.next_check_at == NOW + timedelta(days=1)
    assert history[-1].state.send_readback == "exact"
    assert TEXT not in history[-1].model_dump_json()


def test_reply_screening_and_interview_require_existing_inbound_evidence():
    value, _ = confirm(record())
    assert value.tracking_state.value == "replied" and value.next_check_at is None
    value, _ = confirm(value, "screening_confirmed")
    assert value.tracking_state.value == "screening"
    value, _ = confirm(value, "interview_confirmed", number=2, interview_invite=True)
    assert value.tracking_state.value == "interview"
    assert value.outcome == "interview"


def test_awaiting_cannot_jump_directly_to_interview_even_with_an_invitation():
    with pytest.raises(ContractValidationError):
        confirm(record(), "interview_confirmed", interview_invite=True)


def test_unread_counter_alone_is_only_suspected_reply():
    value, _ = apply(record(), "suspected_reply", evidence_kind="unread_count")
    assert value.tracking_state.value == "awaiting_reply" and value.check_count == 0
    with pytest.raises(ContractValidationError):
        apply(value, "reply_confirmed", evidence_kind="unread_count")


def test_no_response_requires_four_effective_checks_and_fourteen_days():
    value = record()
    for count, day in enumerate([1, 3, 7], start=1):
        value, _ = apply(value, "no_reply", day)
        assert value.check_count == count and value.tracking_state.value == "awaiting_reply"
    value, history = apply(value, "no_reply", 14)
    assert [e.state.tracking_state.value for e in history] == ["no_response_expired", "closed"]
    assert value.check_count == 4 and value.outcome == "no_response"
    assert value.next_check_at is None and value.abandon_reason == "no_response_expired"


def test_missed_checks_are_not_inflated_by_four_reads_in_one_round():
    value, _ = apply(record(), "no_reply", 14)
    assert value.check_count == 1 and value.tracking_state.value == "awaiting_reply"
    with pytest.raises(ContractValidationError):
        apply(value, "no_reply", 14, event_id="SECOND", observation_id="SECOND")
    for day in [15, 16, 17]:
        value, _ = apply(value, "no_reply", day)
    assert value.tracking_state.value == "closed"


def test_four_checks_before_day_fourteen_do_not_expire_early():
    value = record().model_copy(update={"check_count": 3, "next_check_at": NOW + timedelta(days=7)})
    value, _ = apply(value, "no_reply", 7)
    assert value.check_count == 4 and value.tracking_state.value == "awaiting_reply"
    assert value.next_check_at == NOW + timedelta(days=14)


@pytest.mark.parametrize("kind", ["user_abandon", "queue_closed"])
def test_explicit_owner_closure_archives_without_erasing_contact(kind):
    value, history = apply(
        record(),
        kind,
        evidence_kind="owner_message",
        owner_text="明确不再跟进这个合成岗位",
    )
    assert value.tracking_state.value == "closed" and value.abandon_reason
    assert value.send_references == ["OAUDIT_DEMO"]
    assert len(history) == 2
    with pytest.raises(ContractValidationError):
        apply(value, "no_reply", 3)


def test_verified_job_closure_and_recruiter_rejection_archive():
    value, _ = apply(
        record(),
        "job_closed",
        evidence_kind="detail_page",
        job_url="https://example.com/synthetic/1",
    )
    assert value.tracking_state.value == "closed" and value.abandon_reason == "job_closed"
    value, _ = confirm(record(), "employer_rejected", declined=True)
    assert value.tracking_state.value == "closed" and value.outcome == "rejected"


def test_anomaly_pauses_and_only_explicit_owner_resume_allows_checks():
    value, _ = apply(record(), "anomaly", day=0, evidence_kind="platform_state")
    assert value.paused and value.next_check_at is None
    with pytest.raises(ContractValidationError):
        apply(value, "no_reply")
    with pytest.raises(ContractValidationError):
        apply(value, "resume", day=0, evidence_kind="owner_message")
    value, _ = apply(
        value,
        "resume",
        day=0,
        evidence_kind="owner_message",
        owner_text="验证已处理，请恢复只读检查",
    )
    assert not value.paused and value.next_check_at == NOW + timedelta(days=1)


def test_same_observation_and_future_clock_do_not_increase_checks():
    from jobagent.jobs.sent_tracking import advance

    value, _ = apply(record(), "no_reply")
    with pytest.raises(ContractValidationError):
        apply(value, "no_reply", 3, observation_id="OBS_2_no_reply")
    future = event(value, "no_reply", 3)
    with pytest.raises(ContractValidationError):
        advance(value, future, now=NOW + timedelta(days=2))


def test_negative_outcome_patterns_are_reports_only_and_require_distinct_jobs():
    from jobagent.jobs.sent_tracking import tracking_report
    from tests.jobs.test_lexicon import features

    closed, _ = apply(record(), "user_abandon", evidence_kind="owner_message", owner_text="停止")
    closed = closed.model_copy(update={"outcome": "no_response"})
    one = tracking_report([closed], [features()])
    assert one["negative_patterns"] == [] and one["changes_search_weights"] is False
    rows = [
        closed.model_copy(update={"job_id": f"JOB_DEMO_{i}", "tracking_id": f"TRACK_{i}"})
        for i in range(1, 4)
    ]
    report = tracking_report(rows, [features(i) for i in range(1, 4)])
    assert report["negative_patterns"]
    assert tracking_report([closed, closed, closed], [features()])["negative_patterns"] == []


def test_inbound_from_before_send_or_after_observation_cannot_count_as_new_reply():
    conversation, inbound = inbound_evidence()
    old = inbound.model_copy(update={"recorded_at": NOW - timedelta(days=1)})
    with pytest.raises(ContractValidationError):
        apply(
            record(),
            "reply_confirmed",
            conversation=conversation,
            inbound=old,
            conversation_id=conversation.conversation_id,
            inbound_event_id=old.event_id,
            evidence_reference=old.event_id,
        )
    future = inbound.model_copy(update={"recorded_at": NOW + timedelta(days=2)})
    with pytest.raises(ContractValidationError):
        apply(
            record(),
            "reply_confirmed",
            conversation=conversation,
            inbound=future,
            conversation_id=conversation.conversation_id,
            inbound_event_id=future.event_id,
            evidence_reference=future.event_id,
        )


def test_reply_round_cannot_use_an_older_send_or_unbound_audit_reference():
    from jobagent.jobs.sent_tracking import advance

    value, _ = confirm(record())
    valid = proof().model_copy(
        update={
            "send_reference": "CEVT_RESULT_NEW",
            "sent_at": NOW + timedelta(days=1),
        }
    )
    update = event(
        value,
        "reply_sent",
        reply_result_event_id=valid.send_reference,
        evidence_reference=valid.send_reference,
        evidence_kind="send_audit",
    )
    assert (
        advance(value, update, now=update.observed_at, reply_proof=valid)[-1].state.round_number
        == 2
    )
    with pytest.raises(ContractValidationError):
        advance(
            value,
            update,
            now=update.observed_at,
            reply_proof=valid.model_copy(update={"sent_at": NOW - timedelta(days=1)}),
        )
    with pytest.raises(ContractValidationError):
        advance(
            value,
            update.model_copy(update={"evidence_reference": "UNRELATED"}),
            now=update.observed_at,
            reply_proof=valid,
        )
