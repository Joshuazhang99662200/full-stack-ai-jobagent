from datetime import timedelta

import pytest
from pydantic import HttpUrl

from jobagent.errors import ContractValidationError
from jobagent.jobs.jd_snapshot import canonical_digest, text_digest
from jobagent.schemas.conversation import (
    Conversation,
    ConversationAsk,
    ConversationEvent,
    EventKind,
    InboundMessage,
    MessageLevel,
    ReplyDraft,
    ReplyKind,
    ReplyResult,
)
from jobagent.schemas.pipeline import PipelineMeta, PipelineObservation, PipelineTransition
from jobagent.storage.conversation_repository import SqliteConversationRepository
from jobagent.storage.database import Database
from tests.jobs.test_pipeline_contracts import NOW, row
from tests.jobs.test_sent_tracking import TEXT, outreach_records


def fixture(tmp_path):
    from jobagent.storage.pipeline_proofs import PipelineProofResolver

    database = Database(tmp_path / "proofs.sqlite3")
    database.migrate()
    job = row(
        job_id="boss-synthetic",
        job_url="https://example.com/synthetic/1",
        draft_greeting=TEXT,
        draft_version="SYNTHETIC_V1",
        draft_digest=text_digest(TEXT),
    )
    meta = PipelineMeta(
        pipeline_id=job.pipeline_id,
        normalized_job_id="JOB_DEMO_1",
        entered_evidence_reference="ENTRY",
    )
    return PipelineProofResolver(database), job, meta


def command(job, **changes):
    data = dict(
        event_id="EVENT_PROOF",
        pipeline_id=job.pipeline_id,
        candidate_id=job.candidate_id,
        expected_version=1,
        from_state="draft_pending",
        to_state="greeting_sent",
        changed_at=NOW,
        evidence_kind="send_audit",
        evidence_reference="OAUDIT_DEMO",
        reason_code="normal",
        send_reference="OAUDIT_DEMO",
        readback_text=TEXT,
    )
    data.update(changes)
    return PipelineTransition.model_validate(data)


def store_outreach(resolver):
    from jobagent.storage.outreach_repository import SqliteOutreachRepository

    store = SqliteOutreachRepository(resolver.database)
    batch, approval, audit = outreach_records()
    # Synthetic audit fixture uses its own now; align it to this test's actual window.
    batch = batch.model_copy(update={"created_at": NOW})
    approval = approval.model_copy(update={"approved_at": NOW})
    audit = audit.model_copy(update={"recorded_at": NOW})
    store.save_batch(batch)
    store.save_approval(approval)
    store.append_audit(audit)


def test_greeting_requires_existing_approval_exact_readback_and_matching_target(tmp_path):
    resolver, job, meta = fixture(tmp_path)
    with pytest.raises(ContractValidationError):
        resolver.resolve(job, meta, command(job), now=NOW)
    store_outreach(resolver)
    proof = resolver.resolve(job, meta, command(job), now=NOW)
    assert (
        proof.sent_text == TEXT and proof.sent_at == NOW and proof.send_reference == "OAUDIT_DEMO"
    )
    for changed in [
        dict(readback_text="wrong"),
        dict(send_reference="OTHER"),
        dict(evidence_reference="OTHER"),
        dict(changed_at=NOW - timedelta(seconds=1)),
    ]:
        with pytest.raises(ContractValidationError):
            resolver.resolve(job, meta, command(job, **changed), now=NOW)
    with pytest.raises(ContractValidationError):
        resolver.resolve(
            job.model_copy(update={"platform": "zhaopin"}), meta, command(job), now=NOW
        )
    with pytest.raises(ContractValidationError):
        resolver.resolve(
            job, meta.model_copy(update={"normalized_job_id": "JOB_OTHER"}), command(job), now=NOW
        )


def inbound_fixture(resolver, job, *, asks_resume=True, invite=False, declined=False):
    store = SqliteConversationRepository(resolver.database)
    conversation = Conversation(
        conversation_id="CONV_PROOF",
        platform="boss",
        job_id="JOB_DEMO_1",
        company=job.company,
        title=job.title,
        origin="outreach",
        opened_at=NOW,
    )
    store.save_conversation(conversation)
    at = NOW + timedelta(hours=1)
    event = ConversationEvent(
        event_id="CEVT_INBOUND",
        conversation_id=conversation.conversation_id,
        seq=1,
        kind=EventKind.INBOUND,
        recorded_at=at,
        inbound=InboundMessage(
            text="Synthetic substantive recruiter reply",
            level=MessageLevel.L1,
            asks_resume=asks_resume,
            interview_invite=invite,
            declined=declined,
            received_at=at,
        ),
    )
    store.append_events([event])
    return store, conversation, event, at


def sent(job):
    return job.model_copy(
        update={
            "pipeline_state": "initial_contact",
            "sent_at": NOW,
            "sent_greeting": TEXT,
            "sent_text_hash": text_digest(TEXT),
            "send_readback": "exact",
        }
    )


def test_inbound_uses_existing_target_bound_message_and_real_source_time(tmp_path):
    resolver, job, meta = fixture(tmp_path)
    _, conv, inbound, at = inbound_fixture(resolver, job)
    job = sent(job)
    event = command(
        job,
        from_state="initial_contact",
        to_state="resume_requested",
        changed_at=at,
        evidence_kind="conversation_message",
        evidence_reference=inbound.event_id,
        conversation_id=conv.conversation_id,
        inbound_event_id=inbound.event_id,
    )
    proof = resolver.resolve(job, meta, event, now=at)
    assert proof.asks_resume and proof.substantive_reply and proof.source_at == at
    for changes in [
        dict(evidence_kind="unread_count"),
        dict(conversation_id="CONV_OTHER"),
        dict(evidence_reference="CEVT_OTHER"),
        dict(inbound_event_id="CEVT_OTHER"),
    ]:
        changed = event.model_copy(update=changes)
        with pytest.raises(ContractValidationError):
            resolver.resolve(job, meta, changed, now=at)
    with pytest.raises(ContractValidationError):
        resolver.resolve(
            job.model_copy(update={"sent_at": at + timedelta(seconds=1)}), meta, event, now=at
        )
    with pytest.raises(ContractValidationError):
        resolver.resolve(job, meta, event, now=NOW)


def test_activity_reset_does_not_invent_a_new_message_time(tmp_path):
    resolver, job, meta = fixture(tmp_path)
    _, conv, inbound, at = inbound_fixture(resolver, job)
    check = at + timedelta(hours=8)
    event = PipelineObservation(
        event_id="RESET",
        pipeline_id=job.pipeline_id,
        candidate_id=job.candidate_id,
        expected_version=1,
        observed_at=check,
        kind="substantive_reply",
        evidence_kind="conversation_message",
        evidence_reference=inbound.event_id,
        conversation_id=conv.conversation_id,
        inbound_event_id=inbound.event_id,
    )
    assert resolver.inbound(sent(job), meta, event, now=check).source_at == at


def test_unconfirmed_flags_and_unverified_read_evidence_are_not_upgraded(tmp_path):
    resolver, job, meta = fixture(tmp_path)
    _, conv, inbound, at = inbound_fixture(resolver, job, asks_resume=False)
    event = command(
        job,
        from_state="initial_contact",
        to_state="resume_requested",
        changed_at=at,
        evidence_kind="conversation_message",
        evidence_reference=inbound.event_id,
        conversation_id=conv.conversation_id,
        inbound_event_id=inbound.event_id,
    )
    assert not resolver.resolve(sent(job), meta, event, now=at).asks_resume
    unread = command(
        job,
        from_state="greeting_sent",
        to_state="greeting_read",
        changed_at=at,
        evidence_kind="conversation_message",
        evidence_reference="BADGE",
    ).model_copy(update={"evidence_kind": "unread_count"})
    with pytest.raises(ContractValidationError):
        resolver.resolve(
            sent(job).model_copy(update={"pipeline_state": "greeting_sent"}),
            meta,
            unread.model_copy(),
            now=at,
        )


def test_read_receipt_or_matching_private_host_capture_is_required(tmp_path):
    from jobagent.schemas.patrol import ConversationReceipt

    resolver, job, meta = fixture(tmp_path)
    store, conv, _, at = inbound_fixture(resolver, job)
    store.record_receipts(
        [
            ConversationReceipt(
                conversation_id=conv.conversation_id,
                status="read",
                observed_at=at,
                snapshot_id="PSNAP_PROOF",
            )
        ]
    )
    event = command(
        job,
        from_state="greeting_sent",
        to_state="greeting_read",
        changed_at=at,
        evidence_kind="conversation_message",
        evidence_reference="PSNAP_PROOF",
        conversation_id=conv.conversation_id,
    )
    assert resolver.resolve(
        sent(job).model_copy(update={"pipeline_state": "greeting_sent"}), meta, event, now=at
    ).read_confirmed
    external = event.model_copy(
        update={
            "conversation_id": None,
            "evidence_reference": "PRIVATE_SCREEN",
            "job_url": job.job_url,
        }
    )
    assert resolver.resolve(
        sent(job).model_copy(update={"pipeline_state": "greeting_sent"}), meta, external, now=at
    ).read_confirmed
    with pytest.raises(ContractValidationError):
        resolver.resolve(
            sent(job).model_copy(update={"pipeline_state": "greeting_sent"}),
            meta,
            external.model_copy(update={"job_url": None}),
            now=at,
        )


def test_owner_completion_and_verified_closure_have_their_own_evidence(tmp_path):
    resolver, job, meta = fixture(tmp_path)
    at = NOW + timedelta(hours=1)
    event = command(
        job,
        from_state="interview_pending",
        to_state="interviewed",
        changed_at=at,
        evidence_kind="owner_message",
        evidence_reference="PRIVATE_COMPLETION",
        owner_text="Interview completed.",
    )
    assert resolver.resolve(
        sent(job).model_copy(update={"pipeline_state": "interview_pending"}), meta, event, now=at
    ).interview_completed
    with pytest.raises(ContractValidationError):
        resolver.resolve(
            sent(job).model_copy(update={"pipeline_state": "interview_pending"}),
            meta,
            event.model_copy(update={"owner_text": None}),
            now=at,
        )
    closure = command(
        job,
        from_state="initial_contact",
        to_state="abandoned",
        changed_at=at,
        evidence_kind="detail_page",
        evidence_reference="PRIVATE_CLOSED_CAPTURE",
        job_url=job.job_url,
        reason_code="job_closed",
    )
    assert resolver.resolve(sent(job), meta, closure, now=at).job_closed
    with pytest.raises(ContractValidationError):
        resolver.resolve(
            sent(job),
            meta,
            closure.model_copy(update={"job_url": HttpUrl("https://example.com/other")}),
            now=at,
        )


def resume_fixture(resolver, job, *, intermediate=None, save_ask=True, reply_kind=ReplyKind.RESUME):
    store, conversation, inbound, at = inbound_fixture(resolver, job)
    pdf = text_digest("Synthetic custom PDF")
    attached = ConversationEvent(
        event_id="CEVT_ATTACHMENT",
        conversation_id=conversation.conversation_id,
        seq=2,
        kind=EventKind.RESUME_ATTACHED,
        recorded_at=at,
        resume_variant_id="RESUME_CUSTOM",
        resume_digest=text_digest("Synthetic verified variant"),
        pdf_digest=pdf,
    )
    reply = ReplyDraft(
        kind=reply_kind, text="Synthetic approved resume reply", in_reply_to=inbound.event_id
    )
    digest = canonical_digest(
        {"conversation": conversation.conversation_id, **reply.model_dump(mode="json")}
    )
    approval = ConversationEvent(
        event_id="CEVT_APPROVAL",
        conversation_id=conversation.conversation_id,
        seq=3,
        kind=EventKind.REPLY_APPROVED,
        recorded_at=at,
        reply=reply,
        reply_digest=digest,
        ask_id="CASK_CUSTOM",
        attestation="Approve this exact resume reply.",
    )
    result = ConversationEvent(
        event_id="CEVT_RESULT",
        conversation_id=conversation.conversation_id,
        seq=4,
        kind=EventKind.REPLY_RESULT,
        recorded_at=at,
        reply_digest=digest,
        result=ReplyResult.SENT,
    )
    if save_ask:
        store.save_ask(
            ConversationAsk(
                ask_id="CASK_CUSTOM",
                conversation_id=conversation.conversation_id,
                subject="reply",
                anchor_seq=2,
                reply=reply,
                reply_digest=digest,
                question="Review this exact synthetic custom resume reply.",
                asked_at=at,
            )
        )
    before = [attached, approval]
    if intermediate == "attachment":
        before.append(
            attached.model_copy(
                update={
                    "event_id": "CEVT_REPLACED",
                    "seq": 4,
                    "pdf_digest": text_digest("Replacement PDF"),
                }
            )
        )
    elif intermediate == "inbound":
        before.append(inbound.model_copy(update={"event_id": "CEVT_LATER", "seq": 4}))
    if intermediate:
        result = result.model_copy(update={"seq": 5})
    store.append_events([*before, result])
    return conversation, result, reply, pdf, at


def test_resume_send_binds_custom_variant_pdf_and_actual_approved_reply(tmp_path):
    resolver, job, meta = fixture(tmp_path)
    conv, result, reply, pdf, at = resume_fixture(resolver, job)
    event = command(
        job,
        from_state="resume_requested",
        to_state="resume_sent",
        changed_at=at,
        evidence_reference=result.event_id,
        send_reference=result.event_id,
        readback_text=reply.text,
        conversation_id=conv.conversation_id,
        resume_version="RESUME_CUSTOM",
        resume_file_id=pdf,
        attachment_digest=pdf,
    )
    proof = resolver.resolve(
        sent(job).model_copy(update={"pipeline_state": "resume_requested"}), meta, event, now=at
    )
    assert proof.resume_file_id == pdf and proof.resume_version == "RESUME_CUSTOM"
    for changes in [
        dict(attachment_digest=text_digest("wrong")),
        dict(resume_file_id="DEFAULT_RESUME"),
        dict(resume_version="DEFAULT"),
        dict(readback_text="wrong"),
        dict(send_reference="OTHER"),
    ]:
        with pytest.raises(ContractValidationError):
            resolver.resolve(
                sent(job).model_copy(update={"pipeline_state": "resume_requested"}),
                meta,
                event.model_copy(update=changes),
                now=at,
            )


def test_new_contact_round_cannot_reuse_an_old_greeting_audit(tmp_path):
    resolver, job, meta = fixture(tmp_path)
    store_outreach(resolver)
    later = NOW + timedelta(hours=1)
    new_round = job.model_copy(
        update={"entered_at": later, "updated_at": later, "state_changed_at": later}
    )
    with pytest.raises(ContractValidationError):
        resolver.resolve(
            new_round,
            meta.model_copy(update={"contact_round": 2}),
            command(job, changed_at=later),
            now=later,
        )


@pytest.mark.parametrize(
    "changes",
    [
        dict(intermediate="attachment"),
        dict(intermediate="inbound"),
        dict(save_ask=False),
        dict(reply_kind=ReplyKind.ANSWER),
    ],
)
def test_resume_approval_cannot_be_reused_after_context_or_attachment_change(tmp_path, changes):
    resolver, job, meta = fixture(tmp_path)
    conv, result, reply, pdf, at = resume_fixture(resolver, job, **changes)
    event = command(
        job,
        from_state="resume_requested",
        to_state="resume_sent",
        changed_at=at,
        evidence_reference=result.event_id,
        send_reference=result.event_id,
        readback_text=reply.text,
        conversation_id=conv.conversation_id,
        resume_version="RESUME_CUSTOM",
        resume_file_id=pdf,
        attachment_digest=pdf,
    )
    with pytest.raises(ContractValidationError):
        resolver.resolve(
            sent(job).model_copy(update={"pipeline_state": "resume_requested"}), meta, event, now=at
        )


def test_resume_source_time_is_the_actual_result_not_later_adoption_time(tmp_path):
    resolver, job, meta = fixture(tmp_path)
    conv, result, reply, pdf, at = resume_fixture(resolver, job)
    adopted_at = at + timedelta(hours=8)
    event = command(
        job,
        from_state="resume_requested",
        to_state="resume_sent",
        changed_at=adopted_at,
        evidence_reference=result.event_id,
        send_reference=result.event_id,
        readback_text=reply.text,
        conversation_id=conv.conversation_id,
        resume_version="RESUME_CUSTOM",
        resume_file_id=pdf,
        attachment_digest=pdf,
    )
    proof = resolver.resolve(
        sent(job).model_copy(update={"pipeline_state": "resume_requested"}),
        meta,
        event,
        now=adopted_at,
    )
    assert proof.sent_at == at and proof.source_at == at


def test_owner_can_close_an_unproven_legacy_declaration_without_fabricating_a_job(tmp_path):
    resolver, job, meta = fixture(tmp_path)
    legacy = job.model_copy(update={"pipeline_state": "greeting_sent"})
    pending = meta.model_copy(update={"proof_status": "proof_pending", "normalized_job_id": None})
    event = command(
        job,
        from_state="greeting_sent",
        to_state="abandoned",
        evidence_kind="owner_message",
        evidence_reference="PRIVATE_OWNER_DECISION",
        reason_code="user_abandoned",
        owner_text="Stop this contact round.",
    )
    assert resolver.resolve(legacy, pending, event, now=NOW).owner_decision


def test_blank_reference_cannot_become_a_host_read_receipt(tmp_path):
    resolver, job, meta = fixture(tmp_path)
    event = command(
        job,
        from_state="greeting_sent",
        to_state="greeting_read",
        evidence_kind="conversation_message",
        evidence_reference="   ",
        job_url=job.job_url,
    )
    with pytest.raises(ContractValidationError):
        resolver.resolve(
            sent(job).model_copy(update={"pipeline_state": "greeting_sent"}), meta, event, now=NOW
        )
