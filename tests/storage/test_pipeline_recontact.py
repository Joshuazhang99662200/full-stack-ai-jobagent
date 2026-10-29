"""Synthetic existing-conversation evidence; these tests never send a message."""

import json
from datetime import timedelta

import pytest

from jobagent.conversation.service import ConversationService
from jobagent.errors import ContractValidationError
from jobagent.jobs.jd_snapshot import text_digest
from jobagent.schemas.conversation import (
    ConversationStage,
    EventKind,
    InboundMessage,
    MessageLevel,
    ReplyDraft,
    ReplyKind,
    ReplyResult,
)
from jobagent.storage.conversation_repository import SqliteConversationRepository
from tests.storage.test_pipeline_sync import NOW, fixture, request, synchronizer


def prepared(tmp_path, *, kind=ReplyKind.FOLLOW_UP, old=False):
    intake, row, snapshot, pipeline, first, meta = fixture(tmp_path)
    # Arrange a prior terminal round; creation and the new reply use real services.
    closed = first.model_copy(
        update={"pipeline_state": "abandoned", "state_reason": "user_abandoned"}
    )
    with intake.database.connect() as connection, connection:
        pipeline.repository.write_job(
            connection, closed, meta.model_copy(update={"abandoned_at": NOW})
        )
    at = NOW + timedelta(hours=1)
    job, metadata = pipeline.create(
        dict(
            event_id="RECONTACT_ENTRY",
            candidate_id=first.candidate_id,
            normalized_job_id=row.job_id,
            intake_id=row.intake_id,
            evidence_reference="PRIVATE_RECONTACT",
            salary_minimum_k=18,
            recontact_owner_text="Contact this role again.",
            recontact_owner_reference="OWNER_CHOICE",
        ),
        now=at,
    )
    core = ConversationService()
    store = SqliteConversationRepository(intake.database)
    conversation, opening = core.adopt_self(
        platform=job.platform,
        company=job.company,
        title=job.title,
        job_id=row.job_id,
        replied=False,
        now=NOW,
    )
    store.save_conversation(conversation)
    store.append_events([opening])
    if kind != ReplyKind.FOLLOW_UP:
        message = InboundMessage(text="Synthetic question", level=MessageLevel.L1, received_at=at)
        store.append_events(
            core.receive(
                conversation, store.list_events(conversation.conversation_id), message, now=at
            )
        )
    events = store.list_events(conversation.conversation_id)
    latest = next((e for e in reversed(events) if e.kind == EventKind.INBOUND), None)
    reply = ReplyDraft(
        kind=kind,
        text="Synthetic approved follow-up content.",
        in_reply_to=latest.event_id if latest else None,
    )
    asked_at = at - timedelta(seconds=2) if old else at + timedelta(seconds=1)
    approved_at = at - timedelta(seconds=1) if old else at + timedelta(seconds=2)
    ask = core.draft_reply(
        conversation, events, reply, now=asked_at, harness_version="HVER_SYNTHETIC_REPLY"
    )
    store.save_ask(ask)
    approval = core.approve_reply(
        conversation, events, ask, answer="Send this exact reply.", now=approved_at
    )
    store.append_events([approval])
    payload = dict(
        event_id="BIND_REPLY",
        candidate_id=job.candidate_id,
        pipeline_id=job.pipeline_id,
        expected_version=metadata.version,
        conversation_id=conversation.conversation_id,
        approval_event_id=approval.event_id,
    )
    return (
        intake,
        row,
        snapshot,
        pipeline,
        job,
        metadata,
        store,
        conversation,
        ask,
        approval,
        payload,
    )


def binding(database):
    from jobagent.storage.pipeline_recontact import PipelineRecontactService

    return PipelineRecontactService(database)


def record_sent(store, conversation, at):
    core = ConversationService()
    events = store.list_events(conversation.conversation_id)
    assert core.reply_gate(conversation, events, lease_held=True, platform_halted=False).allowed
    result = core.record_reply(conversation, events, result=ReplyResult.SENT, reason=None, now=at)[
        0
    ]
    store.append_events([result])
    return result


def transition(pipeline, job, meta, conversation, result, text, at, **changes):
    data = dict(
        event_id="RECONTACT_SENT",
        candidate_id=job.candidate_id,
        pipeline_id=job.pipeline_id,
        expected_version=meta.version,
        from_state="draft_pending",
        to_state="greeting_sent",
        changed_at=at,
        evidence_kind="send_audit",
        evidence_reference=result.event_id,
        send_reference=result.event_id,
        conversation_id=conversation.conversation_id,
        readback_text=text,
        reason_code="normal",
    )
    data.update(changes)
    return pipeline.transition(data, now=at)


@pytest.mark.parametrize("kind", [ReplyKind.FOLLOW_UP, ReplyKind.ANSWER])
def test_existing_approved_reply_binds_new_round_then_real_result_advances_once(tmp_path, kind):
    intake, _, _, pipeline, job, _meta, store, conv, ask, approval, payload = prepared(
        tmp_path, kind=kind
    )
    original_events = store.list_events(conv.conversation_id)
    bound = binding(intake.database).bind_reply(payload, now=job.entered_at + timedelta(seconds=3))
    assert bound[0].pipeline_state == "draft_pending" and bound[0].sent_at is None
    assert bound[0].draft_greeting == approval.reply.text
    assert bound[0].draft_digest == text_digest(approval.reply.text)
    assert bound[0].draft_version == approval.harness_version
    assert bound[1].recontact_approval_event_id == approval.event_id
    assert bound[1].recontact_reply_digest == approval.reply_digest
    assert (
        binding(intake.database).bind_reply(payload, now=job.entered_at + timedelta(seconds=4))
        == bound
    )
    assert store.list_events(conv.conversation_id) == original_events
    assert store.get_ask(ask.ask_id) == ask
    assert len(pipeline.repository.history(job.pipeline_id, job.candidate_id)) == 1
    with intake.database.connect() as connection:
        artifact = connection.execute(
            "SELECT observation_json FROM pipeline_observations WHERE event_id = ?",
            (payload["event_id"],),
        ).fetchone()
        assert json.loads(artifact[0])["kind"] == "artifact_sync"
    sent_at = job.entered_at + timedelta(seconds=5)
    result = record_sent(store, conv, sent_at)
    sent = transition(pipeline, *bound, conv, result, approval.reply.text, sent_at)
    assert sent[0].sent_at == sent_at and sent[0].pipeline_state == "greeting_sent"
    assert (
        sent[1].proof_status == "verified"
        and sent[1].sent_greeting_version == approval.harness_version
    )
    assert transition(pipeline, *bound, conv, result, approval.reply.text, sent_at) == sent
    assert len(pipeline.repository.history(job.pipeline_id, job.candidate_id)) == 2


@pytest.mark.parametrize(
    "fault",
    [
        "old",
        "wrong_job",
        "wrong_candidate",
        "first_round",
        "no_ask",
        "bad_anchor",
        "empty_attestation",
        "closed",
        "declined",
        "inbound",
        "attachment",
        "resume",
    ],
)
def test_binding_rejects_stale_wrong_target_or_invalid_existing_approval(tmp_path, fault):
    intake, _, _, pipeline, job, meta, store, conv, ask, approval, payload = (
        prepared(
            tmp_path,
            old=fault == "old",
            kind=ReplyKind.RESUME if fault == "resume" else ReplyKind.FOLLOW_UP,
        )
        if fault != "resume"
        else prepared(tmp_path)
    )
    if fault == "wrong_candidate":
        payload["candidate_id"] = "CAND_OTHER"
    elif fault == "wrong_job":
        metadata = meta.model_copy(update={"normalized_job_id": "JOB_OTHER"})
        with intake.database.connect() as connection, connection:
            pipeline.repository.write_job(connection, job, metadata)
    elif fault == "first_round":
        with intake.database.connect() as connection, connection:
            pipeline.repository.write_job(
                connection, job, meta.model_copy(update={"contact_round": 1})
            )
    elif fault == "no_ask":
        with intake.database.connect() as connection, connection:
            connection.execute("DELETE FROM conversation_asks WHERE ask_id = ?", (ask.ask_id,))
    elif fault == "bad_anchor":
        store.save_ask(ask.model_copy(update={"anchor_seq": approval.seq}))
    elif fault == "empty_attestation":
        with intake.database.connect() as connection, connection:
            changed = approval.model_copy(update={"attestation": " "})
            connection.execute(
                "UPDATE conversation_events SET event_json = ? WHERE event_id = ?",
                (changed.model_dump_json(), approval.event_id),
            )
    elif fault in {"closed", "declined"}:
        events = store.list_events(conv.conversation_id)
        store.append_events(
            [
                ConversationService().transition(
                    conv,
                    events,
                    ConversationStage.CLOSED if fault == "closed" else ConversationStage.DECLINED,
                    reason="Synthetic terminal state",
                    now=job.entered_at + timedelta(seconds=3),
                )
            ]
        )
    elif fault in {"inbound", "attachment"}:
        from jobagent.schemas.conversation import ConversationEvent

        if fault == "inbound":
            store.append_events(
                ConversationService().receive(
                    conv,
                    store.list_events(conv.conversation_id),
                    InboundMessage(
                        text="New context", level=MessageLevel.L1, received_at=job.entered_at
                    ),
                    now=job.entered_at + timedelta(seconds=3),
                )
            )
        else:
            store.append_events(
                [
                    ConversationEvent(
                        event_id="CEVT_ATTACHMENT",
                        conversation_id=conv.conversation_id,
                        seq=approval.seq + 1,
                        kind=EventKind.RESUME_ATTACHED,
                        recorded_at=job.entered_at + timedelta(seconds=3),
                        resume_variant_id="RESUME_SYNTHETIC",
                        resume_digest=text_digest("variant"),
                        pdf_digest=text_digest("pdf"),
                    )
                ]
            )
    elif fault == "resume":
        with intake.database.connect() as connection, connection:
            reply = approval.reply.model_copy(update={"kind": ReplyKind.RESUME})
            changed = approval.model_copy(update={"reply": reply})
            connection.execute(
                "UPDATE conversation_events SET event_json = ? WHERE event_id = ?",
                (changed.model_dump_json(), approval.event_id),
            )
    with pytest.raises(ContractValidationError):
        binding(intake.database).bind_reply(payload, now=job.entered_at + timedelta(seconds=4))
    assert (
        pipeline.repository.get(job.pipeline_id, job.candidate_id)[0].pipeline_state
        == "draft_pending"
    )


def test_new_inbound_after_binding_blocks_old_sent_result(tmp_path):
    intake, _, _, pipeline, job, _, store, conv, _, approval, payload = prepared(tmp_path)
    bound = binding(intake.database).bind_reply(payload, now=job.entered_at + timedelta(seconds=3))
    # Existing recording semantics remain unchanged; stale evidence cannot advance the pipeline.
    store.append_events(
        ConversationService().receive(
            conv,
            store.list_events(conv.conversation_id),
            InboundMessage(
                text="Changed context", level=MessageLevel.L1, received_at=job.entered_at
            ),
            now=job.entered_at + timedelta(seconds=4),
        )
    )
    result = ConversationService().record_reply(
        conv,
        store.list_events(conv.conversation_id),
        result=ReplyResult.SENT,
        reason=None,
        now=job.entered_at + timedelta(seconds=5),
    )[0]
    store.append_events([result])
    with pytest.raises(ContractValidationError):
        transition(pipeline, *bound, conv, result, approval.reply.text, result.recorded_at)


def test_sync_preserves_bound_reply_and_clears_it_when_pending_jd_changes(tmp_path):
    from jobagent.schemas.jd_snapshot import JDSnapshotInput

    intake, row, snapshot, _pipeline, job, _, _, _, _, approval, payload = prepared(tmp_path)
    bound = binding(intake.database).bind_reply(payload, now=job.entered_at + timedelta(seconds=3))
    refreshed = synchronizer(intake.database).sync(
        request(*bound, event_id="SYNC_REPLY"), now=job.entered_at + timedelta(seconds=4)
    )
    assert refreshed[0].draft_greeting == approval.reply.text != row.draft.text
    assert refreshed[1].recontact_approval_event_id == approval.event_id
    cached = intake.jobs.get_job(row.job_id)
    new_text = snapshot.jd_text + " Different actual responsibility."
    intake.jobs.save_job(cached.model_copy(update={"jd_raw": new_text}))
    data = snapshot.model_dump(
        exclude={"snapshot_id", "snapshot_version", "jd_text_hash", "content_digest"}
    )
    data.update(
        observation_id="RECONTACT_NEW_JD",
        jd_text=new_text,
        fetched_at=job.entered_at + timedelta(seconds=5),
    )
    intake.knowledge.capture(JDSnapshotInput.model_validate(data))
    changed = synchronizer(intake.database).sync(
        request(*refreshed, event_id="SYNC_CHANGED_JD"), now=job.entered_at + timedelta(seconds=6)
    )
    assert changed[0].draft_greeting is None and changed[0].draft_digest is None
    assert (
        changed[1].recontact_approval_event_id is None
        and changed[1].recontact_conversation_id is None
    )
    assert changed[1].paused and changed[1].pause_reason == "recontact_jd_changed"
    with pytest.raises(ContractValidationError):
        binding(intake.database).bind_reply(
            {
                **payload,
                "event_id": "OLD_APPROVAL_AFTER_JD_CHANGE",
                "expected_version": changed[1].version,
            },
            now=job.entered_at + timedelta(seconds=7),
        )


def test_bound_recontact_readback_mismatch_pauses_without_advancing_or_resending(tmp_path):
    intake, _, _, pipeline, job, _, store, conv, _, _approval, payload = prepared(tmp_path)
    bound = binding(intake.database).bind_reply(payload, now=job.entered_at + timedelta(seconds=3))
    result = record_sent(store, conv, job.entered_at + timedelta(seconds=5))
    original_events = store.list_events(conv.conversation_id)
    with pytest.raises(ContractValidationError) as raised:
        transition(pipeline, *bound, conv, result, "wrong readback", result.recorded_at)
    assert raised.value.details.get("reason") == "readback_mismatch"
    current = pipeline.repository.get(job.pipeline_id, job.candidate_id)
    assert current[1].paused and current[0].pipeline_state == "draft_pending"
    assert current[0].sent_at is None and store.list_events(conv.conversation_id) == original_events
    with pytest.raises(ContractValidationError):
        transition(pipeline, *bound, conv, result, "wrong readback", result.recorded_at)
    assert (
        pipeline.repository.get(job.pipeline_id, job.candidate_id)[1].version == current[1].version
    )


def test_unbound_reply_cannot_replace_an_ordinary_first_greeting(tmp_path):
    intake, _, _, pipeline, job, meta, store, conv, _, approval, _ = prepared(tmp_path)
    first_round = meta.model_copy(update={"contact_round": 1})
    with intake.database.connect() as connection, connection:
        pipeline.repository.write_job(connection, job, first_round)
    result = record_sent(store, conv, job.entered_at + timedelta(seconds=5))
    with pytest.raises(ContractValidationError):
        transition(
            pipeline, job, first_round, conv, result, approval.reply.text, result.recorded_at
        )
    assert pipeline.repository.get(job.pipeline_id, job.candidate_id)[1].version == 1
