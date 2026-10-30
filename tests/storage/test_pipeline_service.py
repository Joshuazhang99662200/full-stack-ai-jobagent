from datetime import timedelta

import pytest

from jobagent.errors import ContractValidationError
from tests.storage.test_job_intake_service import NOW, command, policy, setup


def test_create_sync_and_private_candidate_isolation(tmp_path):
    from jobagent.storage.pipeline_service import PipelineService

    service, intake, snapshot = setup(tmp_path)
    intake = service.attach_snapshot(command(intake, snapshot_id=snapshot.snapshot_id), now=NOW)
    intake = service.factorize(command(intake), policy(), proposal=None, now=NOW)
    pipeline = PipelineService(service.database)
    data = dict(
        event_id="CREATE_PIPE",
        candidate_id="CAND_DEMO",
        normalized_job_id=intake.job_id,
        intake_id=intake.intake_id,
        evidence_reference="OWNER_ENTRY",
        salary_minimum_k=18,
    )
    job, meta = pipeline.create(data, now=NOW)
    assert job.pipeline_state == "draft_pending" and job.jd_text == snapshot.jd_text
    assert job.salary_verified == "review" and job.sent_at is None
    assert job.job_id == "boss-1" and meta.domain == "design"
    assert pipeline.create(data, now=NOW + timedelta(seconds=1)) == (job, meta)
    assert meta.feature_set_id == intake.feature_set_id
    with pytest.raises(ContractValidationError):
        pipeline.create({**data, "event_id": "WRONG", "candidate_id": "CAND_OTHER"}, now=NOW)


def test_new_contact_cannot_be_built_for_unsupported_or_missing_identity(tmp_path):
    from jobagent.storage.pipeline_service import PipelineService

    service, _, _ = setup(tmp_path)
    pipeline = PipelineService(service.database)
    with pytest.raises(ContractValidationError):
        pipeline.create(
            dict(
                event_id="CREATE",
                candidate_id="CAND_DEMO",
                normalized_job_id="JOB_MISSING",
                salary_minimum_k=18,
                evidence_reference="ENTRY",
            ),
            now=NOW,
        )


def test_transition_validation_is_logged_without_private_text(tmp_path):
    from jobagent.storage.pipeline_service import PipelineService

    service, _, _ = setup(tmp_path)
    pipeline = PipelineService(service.database)
    with pytest.raises(ContractValidationError):
        pipeline.transition(
            dict(
                event_id="BAD",
                from_state="draft_pending",
                to_state="interviewed",
                owner_text="PRIVATE_TEXT",
            ),
            now=NOW,
        )
    with service.database.connect() as connection:
        row = connection.execute("SELECT * FROM pipeline_rejections").fetchone()
        assert row and "PRIVATE_TEXT" not in str(dict(row))


def test_legacy_send_binding_requires_exact_proof_and_never_fabricates_a_send_time(tmp_path):
    from jobagent.jobs.jd_snapshot import text_digest
    from jobagent.schemas.jobs import NormalizedJob
    from jobagent.storage.job_repository import SqliteJobRepository
    from jobagent.storage.pipeline_repository import PipelineRepository
    from jobagent.storage.pipeline_service import PipelineService
    from tests.storage.test_pipeline_proofs import TEXT, fixture, store_outreach

    resolver, job, meta = fixture(tmp_path)
    store_outreach(resolver)
    jobs = SqliteJobRepository(resolver.database)
    jobs.save_job(
        NormalizedJob(
            id="JOB_DEMO_1",
            source="boss",
            source_job_id="synthetic",
            title=job.title,
            company=job.company,
            location="Synthetic city",
            url=job.job_url,
            jd_raw="Synthetic complete source text",
            collected_at=NOW,
            provenance=[dict(source="boss", source_id="synthetic", collected_at=NOW)],
        )
    )
    repository = PipelineRepository(resolver.database)
    repository.create(job, meta, event_id="ENTRY", evidence_reference="SOURCE")
    declared = job.model_copy(update={"pipeline_state": "greeting_sent"})
    metadata = meta.model_copy(
        update={"proof_status": "proof_pending", "source_job_id": "synthetic"}
    )
    with resolver.database.connect() as connection, connection:
        repository.write_job(connection, declared, metadata)
    service = PipelineService(resolver.database)
    payload = dict(
        event_id="BIND",
        pipeline_id=job.pipeline_id,
        candidate_id=job.candidate_id,
        expected_version=1,
        normalized_job_id="JOB_DEMO_1",
        audit_id="OAUDIT_DEMO",
        readback_text=TEXT,
    )
    with pytest.raises(ContractValidationError):
        service.bind_send(
            {**payload, "readback_text": "wrong"}, now=job.entered_at + timedelta(hours=1)
        )
    paused = repository.get(job.pipeline_id, job.candidate_id)
    assert paused[1].proof_status == "proof_pending" and paused[1].paused
    assert paused[0].pipeline_state == "greeting_sent" and paused[0].sent_at is None
    payload["expected_version"] = paused[1].version
    bound = service.bind_send(payload, now=job.entered_at + timedelta(hours=1))
    assert bound[0].sent_at == job.entered_at and bound[0].sent_text_hash == text_digest(TEXT)
    assert bound[1].proof_status == "verified" and bound[0].pipeline_state == "greeting_sent"
    assert bound[1].paused  # Binding evidence does not silently resume the host.
    assert service.bind_send(payload, now=job.entered_at + timedelta(hours=2)) == bound
    assert len(repository.history(job.pipeline_id, job.candidate_id)) == 1
    resumed = service.observe(
        dict(
            event_id="OWNER_AFTER_BIND",
            pipeline_id=job.pipeline_id,
            candidate_id=job.candidate_id,
            expected_version=bound[1].version,
            kind="resume",
            observed_at=job.entered_at + timedelta(hours=2),
            evidence_kind="owner_message",
            evidence_reference="PRIVATE_OWNER_RESUME",
            owner_text="Checked original readback, resume.",
        ),
        now=job.entered_at + timedelta(hours=2),
    )
    closed = service.transition(
        dict(
            event_id="OWNER_CLOSE_BOUND",
            pipeline_id=job.pipeline_id,
            candidate_id=job.candidate_id,
            expected_version=resumed[1].version,
            from_state="greeting_sent",
            to_state="abandoned",
            changed_at=job.entered_at + timedelta(hours=3),
            evidence_kind="owner_message",
            evidence_reference="PRIVATE_OWNER_CLOSE",
            reason_code="user_abandoned",
            owner_text="Stop this contact.",
        ),
        now=job.entered_at + timedelta(hours=3),
    )
    with pytest.raises(ContractValidationError):
        service.bind_send(
            {
                **payload,
                "event_id": "TERMINAL_MISMATCH",
                "expected_version": closed[1].version,
                "readback_text": "wrong",
            },
            now=job.entered_at + timedelta(hours=4),
        )
    assert repository.get(job.pipeline_id, job.candidate_id) == closed


def proof_service(tmp_path):
    from jobagent.storage.pipeline_repository import PipelineRepository
    from jobagent.storage.pipeline_service import PipelineService
    from tests.storage.test_pipeline_proofs import fixture, store_outreach

    resolver, job, meta = fixture(tmp_path)
    store_outreach(resolver)
    repository = PipelineRepository(resolver.database)
    repository.create(job, meta, event_id="SYNTHETIC_ENTRY", evidence_reference="ENTRY")
    return PipelineService(resolver.database), resolver, job, meta


def test_matching_readback_mismatch_pauses_original_state_once_until_owner_resumes(tmp_path):
    from tests.storage.test_pipeline_proofs import TEXT, command

    service, _, job, _ = proof_service(tmp_path)
    at = job.entered_at + timedelta(hours=1)
    bad = command(job, changed_at=at, readback_text="PRIVATE_WRONG_READBACK").model_dump()
    with pytest.raises(ContractValidationError) as raised:
        service.transition(bad, now=at)
    assert raised.value.details.get("reason") == "readback_mismatch"
    current, metadata = service.repository.get(job.pipeline_id, job.candidate_id)
    assert current.pipeline_state == "draft_pending" and current.sent_at is None
    assert metadata.paused and metadata.version == 2
    assert len(service.repository.history(job.pipeline_id, job.candidate_id)) == 1
    with pytest.raises(ContractValidationError):
        service.transition(bad, now=at + timedelta(minutes=1))
    assert service.repository.get(job.pipeline_id, job.candidate_id)[1].version == 2
    good = command(
        job,
        event_id="ACTUAL_CONFIRMED_READBACK",
        expected_version=2,
        changed_at=at + timedelta(minutes=1),
        readback_text=TEXT,
    ).model_dump()
    with pytest.raises(ContractValidationError):
        service.transition(good, now=at + timedelta(minutes=1))
    assert (
        service.repository.get(job.pipeline_id, job.candidate_id)[0].pipeline_state
        == "draft_pending"
    )
    resumed = service.observe(
        dict(
            event_id="OWNER_RESUME_READBACK",
            pipeline_id=job.pipeline_id,
            candidate_id=job.candidate_id,
            expected_version=2,
            kind="resume",
            observed_at=at + timedelta(minutes=2),
            evidence_kind="owner_message",
            evidence_reference="PRIVATE_OWNER_REPLY",
            owner_text="Readback checked, resume.",
        ),
        now=at + timedelta(minutes=2),
    )
    good.update(expected_version=resumed[1].version, changed_at=at + timedelta(minutes=3))
    result = service.transition(good, now=at + timedelta(minutes=3))
    assert result[0].pipeline_state == "greeting_sent" and not result[1].paused
    assert service.transition(good, now=at + timedelta(minutes=4)) == result


def test_wrong_target_or_unknown_send_cannot_pause_the_current_pipeline(tmp_path):
    from jobagent.jobs.jd_snapshot import canonical_digest
    from jobagent.storage.outreach_repository import SqliteOutreachRepository
    from tests.jobs.test_sent_tracking import outreach_records
    from tests.storage.test_pipeline_proofs import command

    service, _, job, _ = proof_service(tmp_path)
    batch, approval, audit = outreach_records()
    item = batch.items[0].model_copy(
        update={"job_id": "JOB_OTHER", "url": "https://example.com/other"}
    )
    batch = batch.model_copy(
        update={
            "batch_id": "OBATCH_OTHER",
            "created_at": job.entered_at,
            "items": [item],
            "batch_digest": canonical_digest([[item.number, item.item_digest]]),
        }
    )
    approval = approval.model_copy(
        update={
            "batch_id": batch.batch_id,
            "batch_digest": batch.batch_digest,
            "approval_id": "OAPPROVAL_OTHER",
            "approved_at": job.entered_at,
        }
    )
    audit = audit.model_copy(
        update={
            "audit_id": "OAUDIT_OTHER",
            "batch_id": batch.batch_id,
            "job_id": item.job_id,
            "approval_id": approval.approval_id,
            "recorded_at": job.entered_at,
        }
    )
    store = SqliteOutreachRepository(service.database)
    store.save_batch(batch)
    store.save_approval(approval)
    store.append_audit(audit)
    for reference in (audit.audit_id, "OAUDIT_MISSING"):
        event = command(
            job,
            send_reference=reference,
            evidence_reference=reference,
            changed_at=job.entered_at + timedelta(hours=1),
            readback_text="wrong",
        )
        with pytest.raises(ContractValidationError):
            service.transition(event.model_dump(), now=job.entered_at + timedelta(hours=1))
    current, metadata = service.repository.get(job.pipeline_id, job.candidate_id)
    assert (
        not metadata.paused and metadata.version == 1 and current.pipeline_state == "draft_pending"
    )


def test_matching_resume_readback_mismatch_pauses_without_recording_attachment_sent(tmp_path):
    from tests.storage.test_pipeline_proofs import command, resume_fixture, sent

    service, resolver, job, meta = proof_service(tmp_path)
    conv, result, _reply, pdf, at = resume_fixture(resolver, job)
    waiting = sent(job).model_copy(update={"pipeline_state": "resume_requested"})
    verified = meta.model_copy(update={"proof_status": "verified"})
    with service.database.connect() as connection, connection:
        service.repository.write_job(connection, waiting, verified)
    event = command(
        job,
        from_state="resume_requested",
        to_state="resume_sent",
        changed_at=at,
        send_reference=result.event_id,
        evidence_reference=result.event_id,
        conversation_id=conv.conversation_id,
        readback_text="PRIVATE_WRONG_RESUME_REPLY",
        resume_version="RESUME_CUSTOM",
        resume_file_id=pdf,
        attachment_digest=pdf,
    )
    with pytest.raises(ContractValidationError) as raised:
        service.transition(event.model_dump(), now=at)
    assert raised.value.details.get("reason") == "readback_mismatch"
    current, metadata = service.repository.get(job.pipeline_id, job.candidate_id)
    assert (
        metadata.paused
        and current.pipeline_state == "resume_requested"
        and current.resume_sent_at is None
    )
    assert current.resume_file_id is None


def test_preserved_legacy_job_prefix_cannot_create_a_second_active_provider_job(tmp_path):
    from jobagent.schemas.pipeline import PipelineMeta
    from jobagent.storage.pipeline_repository import PipelineRepository
    from jobagent.storage.pipeline_service import PipelineService
    from tests.jobs.test_pipeline_contracts import row as pipeline_row

    intake, current, _ = setup(tmp_path)
    cached = intake.jobs.get_job(current.job_id)
    legacy = pipeline_row(
        pipeline_id="PIPE_1111111111111111",
        job_id="BOSS-1",
        job_url=cached.url,
        title=cached.title,
        company=cached.company,
        entered_at=NOW,
        state_changed_at=NOW,
        updated_at=NOW,
    )
    meta = PipelineMeta(
        pipeline_id=legacy.pipeline_id,
        normalized_job_id=cached.id,
        source_job_id=cached.source_job_id,
        entered_evidence_reference="LEGACY_SOURCE",
    )
    repo = PipelineRepository(intake.database)
    repo.create(legacy, meta, event_id="LEGACY_ENTRY", evidence_reference="LEGACY_SOURCE")
    with pytest.raises(ContractValidationError):
        PipelineService(intake.database).create(
            dict(
                event_id="NEW_ENTRY",
                candidate_id="CAND_DEMO",
                normalized_job_id=cached.id,
                evidence_reference="CURRENT_PAGE",
                salary_minimum_k=18,
            ),
            now=NOW,
        )
    assert len(repo.list_records("CAND_DEMO")) == 1
