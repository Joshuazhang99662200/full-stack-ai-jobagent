import json
from datetime import timedelta

import pytest

from jobagent.errors import ContractValidationError
from jobagent.jobs.jd_snapshot import text_digest
from jobagent.schemas.pipeline import PipelineTransition, PipelineVerifiedEvidence
from jobagent.storage.pipeline_service import PipelineService
from tests.storage.test_job_intake_service import NOW, command, draft_payload, policy, setup


def fixture(tmp_path, *, complete=True, draft=True):
    intake, row, snapshot = setup(tmp_path)
    if complete:
        row = intake.attach_snapshot(command(row, snapshot_id=snapshot.snapshot_id), now=NOW)
        row = intake.factorize(command(row), policy(), proposal=None, now=NOW)
        if draft:
            row = intake.submit_draft(draft_payload(row), now=NOW)
    pipeline = PipelineService(intake.database)
    job, meta = pipeline.create(
        dict(
            event_id="PIPE_ENTRY",
            candidate_id=row.candidate_id,
            normalized_job_id=row.job_id,
            intake_id=row.intake_id,
            evidence_reference="PRIVATE_ENTRY",
            salary_minimum_k=18,
            jd_points=["Actual source excerpt"],
        ),
        now=NOW,
    )
    return intake, row, snapshot, pipeline, job, meta


def request(job, meta, event_id="SYNC", **changes):
    data = dict(
        event_id=event_id,
        pipeline_id=job.pipeline_id,
        candidate_id=job.candidate_id,
        expected_version=meta.version,
    )
    data.update(changes)
    return data


def synchronizer(database):
    from jobagent.storage.pipeline_sync import PipelineSyncService

    return PipelineSyncService(database)


def test_only_attach_validated_full_snapshot_and_real_features_draft_are_synchronized(tmp_path):
    intake, row, snap, pipeline, job, meta = fixture(tmp_path)
    signal_count = len(intake.repository.signals(row.candidate_id, row.domain))
    updated, metadata = synchronizer(intake.database).sync(
        request(job, meta), now=NOW + timedelta(seconds=1)
    )
    assert updated.jd_text == snap.jd_text and updated.jd_text_hash == snap.jd_text_hash
    assert updated.draft_greeting == row.draft.text and updated.draft_digest == text_digest(
        row.draft.text
    )
    assert updated.draft_version == "CONTENT_" + updated.draft_digest[7:23]
    assert (
        metadata.feature_set_id == row.feature_set_id and metadata.snapshot_id == snap.snapshot_id
    )
    assert metadata.tech == ["Figma"] and metadata.domain == row.domain
    assert updated.pipeline_state == "draft_pending" and updated.sent_at is None
    assert len(pipeline.repository.history(job.pipeline_id, job.candidate_id)) == 1
    assert len(intake.repository.signals(row.candidate_id, row.domain)) == signal_count
    with intake.database.connect() as connection:
        evidence = json.loads(
            connection.execute(
                "SELECT observation_json FROM pipeline_observations WHERE event_id = 'SYNC'"
            ).fetchone()[0]
        )
        assert evidence["kind"] == "artifact_sync" and evidence["source_digest"].startswith(
            "sha256:"
        )


def test_cached_full_text_without_intake_attach_never_promotes_summary_to_full(tmp_path):
    intake, _, _, _, job, meta = fixture(tmp_path, complete=False)
    updated, metadata = synchronizer(intake.database).sync(request(job, meta), now=NOW)
    assert updated.jd_text is None and updated.jd_text_hash is None
    assert json.loads(updated.jd_points) == ["Actual source excerpt"]
    assert updated.draft_greeting is None and metadata.feature_set_id is None
    assert metadata.snapshot_id is None


def test_changed_jd_clears_current_derived_artifacts_but_preserves_actual_send_and_history(
    tmp_path,
):
    from jobagent.schemas.jd_snapshot import JDSnapshotInput

    intake, row, old, pipeline, job, meta = fixture(tmp_path)
    event = PipelineTransition(
        event_id="SEND_EXISTING",
        pipeline_id=job.pipeline_id,
        candidate_id=job.candidate_id,
        expected_version=meta.version,
        from_state="draft_pending",
        to_state="greeting_sent",
        changed_at=NOW,
        evidence_kind="send_audit",
        evidence_reference="AUDIT_EXISTING",
        send_reference="AUDIT_EXISTING",
        reason_code="normal",
    )
    proof = PipelineVerifiedEvidence(
        reference=event.evidence_reference,
        kind="send_audit",
        observed_at=NOW,
        source_at=NOW,
        sent_at=NOW,
        sent_text=job.draft_greeting,
        send_reference=event.send_reference,
    )
    sent, sent_meta = pipeline.repository.transition(event, proof, now=NOW)
    cached = intake.jobs.get_job(row.job_id)
    new_text = old.jd_text + " New confirmed responsibility."
    intake.jobs.save_job(cached.model_copy(update={"jd_raw": new_text}))
    data = old.model_dump(
        exclude={"snapshot_id", "snapshot_version", "jd_text_hash", "content_digest"}
    )
    data.update(observation_id="NEW_JD", jd_text=new_text, fetched_at=NOW + timedelta(seconds=1))
    new = intake.knowledge.capture(JDSnapshotInput.model_validate(data)).snapshot
    updated, metadata = synchronizer(intake.database).sync(
        request(sent, sent_meta), now=NOW + timedelta(seconds=2)
    )
    assert (
        updated.jd_text is None and updated.draft_greeting is None and updated.draft_digest is None
    )
    assert metadata.feature_set_id is None and metadata.tech == [] and metadata.snapshot_id is None
    assert (
        updated.sent_greeting == sent.sent_greeting
        and updated.sent_text_hash == sent.sent_text_hash
    )
    assert updated.sent_at == sent.sent_at and updated.send_readback == sent.send_readback
    assert updated.pipeline_state == "greeting_sent" and metadata.proof_status == "verified"
    assert intake.knowledge.get(old.snapshot_id).jd_text == old.jd_text
    assert new.snapshot_version == old.snapshot_version + 1
    assert len(pipeline.repository.history(job.pipeline_id, job.candidate_id)) == 2


def test_replay_is_bound_to_original_request_even_when_sources_later_change(tmp_path):
    intake, row, _, pipeline, job, meta = fixture(tmp_path)
    sync = synchronizer(intake.database)
    data = request(job, meta)
    original = sync.sync(data, now=NOW)
    revised = draft_payload(row)
    revised["draft"]["text"] += " 方便进一步了解吗?"
    intake.submit_draft(revised, now=NOW + timedelta(seconds=1))
    assert sync.sync(data, now=NOW + timedelta(seconds=2)) == original
    with pytest.raises(ContractValidationError):
        sync.sync(
            request(original[0], original[1], event_id="SYNC_STALE"), now=NOW + timedelta(seconds=2)
        )
    current = pipeline.repository.get(job.pipeline_id, job.candidate_id)
    next_data = request(current[0], current[1], event_id="SYNC_NEW")
    changed = sync.sync(next_data, now=NOW + timedelta(seconds=2))
    assert changed[0].draft_digest != original[0].draft_digest
    assert len(pipeline.repository.history(job.pipeline_id, job.candidate_id)) == 1


def test_wrong_candidate_identity_extra_body_and_terminal_sync_are_rejected(tmp_path):
    from pydantic import ValidationError

    from jobagent.schemas.pipeline_sync import PipelineSyncRequest

    intake, _, _, pipeline, job, meta = fixture(tmp_path)
    with pytest.raises(ValidationError):
        PipelineSyncRequest.model_validate({**request(job, meta), "jd_text": "PRIVATE_INJECTION"})
    with pytest.raises(ContractValidationError):
        synchronizer(intake.database).sync(request(job, meta, candidate_id="CAND_OTHER"), now=NOW)
    with pipeline.database.connect() as connection, connection:
        connection.execute(
            "UPDATE pipeline_meta SET meta_json = "
            "json_set(meta_json, '$.source_job_id', 'other-provider') WHERE pipeline_id = ?",
            (job.pipeline_id,),
        )
    with pytest.raises(ContractValidationError):
        synchronizer(intake.database).sync(request(job, meta), now=NOW)


def test_terminal_pipeline_is_never_revived_by_artifact_sync(tmp_path):
    intake, _, _, pipeline, job, meta = fixture(tmp_path)
    closed = job.model_copy(
        update={"pipeline_state": "abandoned", "state_reason": "user_abandoned"}
    )
    terminal = meta.model_copy(update={"abandoned_at": NOW})
    with pipeline.database.connect() as connection, connection:
        pipeline.repository.write_job(connection, closed, terminal)
    with pytest.raises(ContractValidationError):
        synchronizer(intake.database).sync(request(closed, terminal), now=NOW)
    assert (
        pipeline.repository.get(job.pipeline_id, job.candidate_id)[0].pipeline_state == "abandoned"
    )


def test_private_url_and_provider_binding_can_find_intake_without_title_guessing(tmp_path):
    intake, row, _, pipeline, job, meta = fixture(tmp_path)
    unbound = meta.model_copy(update={"intake_id": None})
    with pipeline.database.connect() as connection, connection:
        pipeline.repository.write_job(connection, job, unbound)
    updated, metadata = synchronizer(intake.database).sync(request(job, unbound), now=NOW)
    assert metadata.intake_id == row.intake_id and updated.draft_digest == text_digest(
        row.draft.text
    )


def test_actual_batch_harness_version_is_used_only_for_the_bound_exact_draft(tmp_path):
    from jobagent.outreach.service import OutreachService

    intake, row, snapshot, pipeline, job, _meta = fixture(tmp_path)
    row = intake.review_draft(
        command(
            row,
            draft_digest=row.draft_digest,
            snapshot_id=snapshot.snapshot_id,
            reviewer_reference="INDEPENDENT_REVIEW",
            review_reference="REVIEW_RESULT",
            accepted=True,
        ),
        now=NOW,
    )
    batch = (
        OutreachService()
        .build_batch(
            [row.draft],
            jobs={row.job_id: intake.job(row)},
            already_contacted=[],
            confirmed_evidence_ids=[],
            batch_id="OBATCH_HARNESS",
            created_at=NOW,
            harness_version="HVER_SYNTHETIC",
        )
        .batch
    )
    intake.outreach.save_batch(batch)
    intake.attach_batch(command(row, batch_id=batch.batch_id), now=NOW)
    current = pipeline.repository.get(job.pipeline_id, job.candidate_id)
    assert current[0].draft_version == "HVER_SYNTHETIC"
    updated, _ = synchronizer(intake.database).sync(request(*current), now=NOW)
    assert updated.draft_version == "HVER_SYNTHETIC"


def test_unknown_private_salary_threshold_keeps_known_raw_salary_in_review(tmp_path):
    from jobagent.schemas.jd_snapshot import JDSnapshotInput

    intake, row, old = setup(tmp_path)
    data = old.model_dump(
        exclude={"snapshot_id", "snapshot_version", "jd_text_hash", "content_digest"}
    )
    data.update(observation_id="SALARY_SOURCE", salary_raw="18-25K")
    salary_snapshot = intake.knowledge.capture(JDSnapshotInput.model_validate(data)).snapshot
    row = intake.attach_snapshot(command(row, snapshot_id=salary_snapshot.snapshot_id), now=NOW)
    pipeline = PipelineService(intake.database)
    job, meta = pipeline.create(
        dict(
            event_id="SALARY_ENTRY",
            candidate_id=row.candidate_id,
            normalized_job_id=row.job_id,
            intake_id=row.intake_id,
            evidence_reference="ENTRY",
            salary_minimum_k=18,
        ),
        now=NOW,
    )
    assert job.salary_verified == "pass"
    unknown = meta.model_copy(update={"salary_minimum_k": None, "salary_currency": None})
    with pipeline.database.connect() as connection, connection:
        pipeline.repository.write_job(connection, job, unknown)
    updated, _ = synchronizer(intake.database).sync(request(job, unknown), now=NOW)
    assert updated.salary_raw == "18-25K" and updated.salary_verified == "review"
    assert updated.salary_min_k is None and updated.salary_max_k is None
