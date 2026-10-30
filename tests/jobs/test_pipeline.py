from datetime import timedelta

import pytest

from jobagent.errors import ContractValidationError
from jobagent.jobs.jd_snapshot import text_digest
from tests.jobs.test_pipeline_contracts import NOW, row


def active(state="greeting_sent", **changes):
    from jobagent.schemas.pipeline import PipelineMeta

    record = row(
        pipeline_state=state,
        sent_greeting="Synthetic sent",
        sent_text_hash=text_digest("Synthetic sent"),
        sent_at=NOW,
        send_readback="exact",
    )
    meta = PipelineMeta(
        pipeline_id=record.pipeline_id,
        proof_status="verified",
        entered_evidence_reference="ENTRY",
        **changes,
    )
    return record, meta


def observation(record, meta, at, **changes):
    from jobagent.schemas.pipeline import PipelineObservation

    data = dict(
        event_id="OBS",
        pipeline_id=record.pipeline_id,
        candidate_id=record.candidate_id,
        expected_version=meta.version,
        observed_at=at,
        kind="no_reply",
        evidence_kind="conversation_message",
        evidence_reference="PRIVATE_READ",
    )
    data.update(changes)
    return PipelineObservation.model_validate(data)


def test_unread_expires_exactly_at_48_hours_without_a_check_count_gate():
    from jobagent.jobs.pipeline import observe_pipeline

    record, meta = active()
    at = NOW + timedelta(hours=48)
    before = observe_pipeline(
        record, meta, observation(record, meta, at - timedelta(seconds=1)), now=at
    )
    assert before[0].pipeline_state == "greeting_sent" and before[2] is None
    expired = observe_pipeline(record, meta, observation(record, meta, at), now=at)
    assert expired[0].pipeline_state == "abandoned" and expired[0].state_reason == "no_reply_2d"
    assert expired[1].abandoned_at == at and expired[1].last_checked_at == at


def test_read_clock_and_substantive_activity_use_later_real_evidence_time():
    from jobagent.jobs.pipeline import observe_pipeline, silence_deadline

    record, meta = active("greeting_read", read_at=NOW + timedelta(hours=6))
    assert silence_deadline(record, meta) == NOW + timedelta(hours=54)
    meta = meta.model_copy(update={"last_substantive_at": NOW + timedelta(hours=30)})
    assert silence_deadline(record, meta) == NOW + timedelta(hours=78)
    result = observe_pipeline(
        record,
        meta,
        observation(record, meta, NOW + timedelta(hours=54)),
        now=NOW + timedelta(hours=54),
    )
    assert result[0].pipeline_state == "greeting_read"


def test_unproven_paused_interviewed_and_abandoned_records_are_not_due():
    from jobagent.jobs.pipeline import observe_pipeline, silence_deadline

    record, meta = active()
    assert (
        silence_deadline(record, meta.model_copy(update={"proof_status": "proof_pending"})) is None
    )
    assert silence_deadline(record, meta.model_copy(update={"paused": True})) is None
    assert (
        silence_deadline(record.model_copy(update={"pipeline_state": "interviewed"}), meta) is None
    )
    closed = record.model_copy(
        update={"pipeline_state": "abandoned", "state_reason": "user_abandoned"}
    )
    assert silence_deadline(closed, meta) is None
    with pytest.raises(ContractValidationError):
        observe_pipeline(
            closed,
            meta,
            observation(closed, meta, NOW + timedelta(days=3)),
            now=NOW + timedelta(days=3),
        )


def test_badge_and_stale_or_future_observations_cannot_confirm_silence():
    from jobagent.jobs.pipeline import observe_pipeline

    record, meta = active()
    at = NOW + timedelta(hours=49)
    for changes in [
        dict(evidence_kind="unread_count"),
        dict(observed_at=NOW - timedelta(seconds=1)),
        dict(observed_at=at + timedelta(seconds=1)),
        dict(expected_version=2),
    ]:
        with pytest.raises(ContractValidationError):
            observe_pipeline(record, meta, observation(record, meta, at, **changes), now=at)


def test_resume_and_rejection_require_target_specific_evidence():
    from jobagent.jobs.pipeline import advance_pipeline
    from jobagent.schemas.pipeline import PipelineTransition, PipelineVerifiedEvidence

    record, meta = active("initial_contact")
    at = NOW + timedelta(hours=1)
    command = PipelineTransition(
        event_id="REQUEST",
        pipeline_id=record.pipeline_id,
        candidate_id=record.candidate_id,
        expected_version=1,
        from_state="initial_contact",
        to_state="resume_requested",
        changed_at=at,
        evidence_kind="conversation_message",
        evidence_reference="INBOUND",
        reason_code="normal",
    )
    evidence = PipelineVerifiedEvidence(
        reference="INBOUND",
        kind="conversation_message",
        observed_at=at,
        source_at=at,
        substantive_reply=True,
    )
    with pytest.raises(ContractValidationError):
        advance_pipeline(record, meta, command, evidence, now=at)
    requested = advance_pipeline(
        record, meta, command, evidence.model_copy(update={"asks_resume": True}), now=at
    )
    assert requested[0].resume_requested and requested[0].resume_requested_at == at
    abandon = PipelineTransition(
        event_id="REJECT",
        pipeline_id=record.pipeline_id,
        candidate_id=record.candidate_id,
        expected_version=1,
        from_state="initial_contact",
        to_state="abandoned",
        changed_at=at,
        evidence_kind="conversation_message",
        evidence_reference="INBOUND",
        reason_code="employer_rejected",
    )
    result = advance_pipeline(
        record, meta, abandon, evidence.model_copy(update={"employer_rejected": True}), now=at
    )
    assert result[0].pipeline_state == "abandoned" and result[0].state_reason == "employer_rejected"


def test_a_new_contact_cannot_adopt_a_send_that_predates_its_entry():
    from jobagent.jobs.pipeline import advance_pipeline
    from jobagent.schemas.pipeline import PipelineMeta, PipelineTransition, PipelineVerifiedEvidence

    job = row(draft_greeting="Synthetic", draft_version="v1", draft_digest=text_digest("Synthetic"))
    meta = PipelineMeta(pipeline_id=job.pipeline_id, entered_evidence_reference="ENTRY")
    event = PipelineTransition(
        event_id="OLD_SEND",
        pipeline_id=job.pipeline_id,
        candidate_id=job.candidate_id,
        expected_version=1,
        from_state="draft_pending",
        to_state="greeting_sent",
        changed_at=NOW,
        evidence_kind="send_audit",
        evidence_reference="OLD_AUDIT",
        reason_code="normal",
    )
    proof = PipelineVerifiedEvidence(
        reference="OLD_AUDIT",
        kind="send_audit",
        observed_at=NOW,
        source_at=NOW - timedelta(hours=1),
        sent_text="Synthetic",
        sent_at=NOW - timedelta(hours=1),
        send_reference="OLD_AUDIT",
    )
    with pytest.raises(ContractValidationError):
        advance_pipeline(job, meta, event, proof, now=NOW)
