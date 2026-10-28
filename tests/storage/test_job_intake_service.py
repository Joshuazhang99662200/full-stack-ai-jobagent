# ruff: noqa: RUF001 -- Preserve synthetic Chinese source punctuation.
from datetime import timedelta

import pytest

from jobagent.errors import ContractValidationError
from tests.storage.test_job_intake import NOW, repository, request

TEXT = "您好，看到岗位负责品牌设计与用户研究，想了解团队当前的设计交付重点。"


def setup(tmp_path, number=1, **request_changes):
    from jobagent.schemas.jd_snapshot import JDSnapshotInput
    from jobagent.schemas.jobs import NormalizedJob
    from jobagent.storage.jd_snapshot_repository import SqliteJDSnapshotRepository
    from jobagent.storage.job_intake_service import JobIntakeService
    from jobagent.storage.job_repository import SqliteJobRepository

    repo = repository(tmp_path)
    service = JobIntakeService(repo.database)
    url = f"https://example.com/jobs/{number}"
    record = repo.enqueue(
        request(request_id=f"REQ_{number}", job_url=url, target_reference=url, **request_changes),
        now=NOW,
    )
    job = NormalizedJob(
        id=f"JOB_DEMO_{number}",
        source="boss",
        source_job_id=str(number),
        title="品牌设计师",
        company=f"合成公司{number}",
        location="上海",
        jd_raw="品牌设计师负责品牌设计、用户研究与Figma设计交付，要求熟悉产品设计。",
        url=url,
        collected_at=NOW - timedelta(days=1),
        provenance=[
            dict(source="boss", source_id=str(number), collected_at=NOW - timedelta(days=1))
        ],
    )
    SqliteJobRepository(repo.database).save_job(job)
    captured = (
        SqliteJDSnapshotRepository(repo.database)
        .capture(
            JDSnapshotInput(
                observation_id=f"OBS_{number}",
                job_id=job.id,
                job_url=url,
                platform="boss",
                fetched_at=job.collected_at,
                title=job.title,
                company=job.company,
                location=job.location,
                jd_text=job.jd_raw,
                completeness="full",
                discovery_kind="manual",
            )
        )
        .snapshot
    )
    record = service.resolve(command(record, job_id=job.id), now=NOW)
    return service, record, captured


def command(row, **changes):
    return dict(
        event_id=f"EV_{row.intake_id}_{row.version}",
        intake_id=row.intake_id,
        candidate_id=row.candidate_id,
        expected_version=row.version,
        **changes,
    )


def policy():
    from jobagent.schemas.lexicon import Lexicon, LexiconTerm

    return Lexicon(
        lexicon_version="v1",
        domain="design",
        updated_at=NOW.date(),
        based_on_snapshots=0,
        based_on_feedback_events=0,
        terms=[
            LexiconTerm(dimension=dim, term=term)
            for dim, term in [("domain", "品牌"), ("role", "设计师"), ("tech", "Figma")]
        ],
    )


def full(tmp_path, **changes):
    service, row, snap = setup(tmp_path, **changes)
    row = service.attach_snapshot(command(row, snapshot_id=snap.snapshot_id), now=NOW)
    return service, row, snap


def draft_payload(row, **changes):
    data = command(
        row,
        draft=dict(job_id=row.job_id, platform="boss", text=TEXT),
        author_reference="AUTHOR_RUN",
        filter_context=dict(candidate_id="CAND_DEMO"),
    )
    data.update(changes)
    return data


def test_resolve_must_match_actual_cached_identity(tmp_path):
    service, row, _ = setup(tmp_path)
    with pytest.raises(ContractValidationError):
        service.resolve(command(row, job_id="JOB_OTHER"), now=NOW)
    assert row.job_url == request(job_url="https://example.com/jobs/1").job_url


def test_partial_or_wrong_snapshot_cannot_unlock_greeting(tmp_path):
    service, row, snap = setup(tmp_path)
    from jobagent.schemas.jd_snapshot import JDSnapshotInput
    from jobagent.storage.jd_snapshot_repository import SqliteJDSnapshotRepository

    data = snap.model_dump(
        exclude={"snapshot_id", "snapshot_version", "jd_text_hash", "content_digest"}
    )
    data.update(observation_id="PARTIAL", completeness="partial", fetched_at=NOW)
    partial = (
        SqliteJDSnapshotRepository(service.database)
        .capture(JDSnapshotInput.model_validate(data))
        .snapshot
    )
    with pytest.raises(ContractValidationError):
        service.attach_snapshot(command(row, snapshot_id=partial.snapshot_id), now=NOW)
    with pytest.raises(ContractValidationError):
        service.submit_draft(draft_payload(row), now=NOW)


def test_new_manual_fetch_requires_real_bound_budget_attempt(tmp_path):
    service, row, snap = setup(tmp_path)
    from jobagent.schemas.jd_snapshot import JDSnapshotInput
    from jobagent.storage.jd_snapshot_repository import SqliteJDSnapshotRepository

    data = snap.model_dump(
        exclude={"snapshot_id", "snapshot_version", "jd_text_hash", "content_digest"}
    )
    data.update(
        observation_id="FRESH",
        jd_text=snap.jd_text + "新增职责。",
        fetched_at=NOW + timedelta(seconds=1),
    )
    store = SqliteJDSnapshotRepository(service.database)
    fresh = store.capture(JDSnapshotInput.model_validate(data)).snapshot
    with pytest.raises(ContractValidationError):
        service.attach_snapshot(
            command(row, snapshot_id=fresh.snapshot_id), now=NOW + timedelta(seconds=2)
        )
    from jobagent.schemas.sourcing import (
        SourcingAttemptRequest,
        SourcingResultRequest,
        SourcingRunRequest,
    )
    from jobagent.storage.sourcing_repository import SqliteSourcingRepository

    meter = SqliteSourcingRepository(service.database)
    meter.start_run(
        SourcingRunRequest(run_id="RUN_ONE", candidate_id=row.candidate_id, source="boss"),
        now=NOW,
        daily_cap=50,
    )
    meter.reserve(
        SourcingAttemptRequest(
            attempt_id="ATT_ONE",
            run_id="RUN_ONE",
            kind="detail",
            source_job_id="1",
            url=row.job_url,
        ),
        now=NOW,
    )
    meter.complete(SourcingResultRequest(attempt_id="ATT_ONE", outcome="gate"), now=NOW)
    with pytest.raises(ContractValidationError):
        service.attach_snapshot(
            command(row, snapshot_id=fresh.snapshot_id, attempt_id="ATT_ONE"),
            now=NOW + timedelta(seconds=2),
        )


def test_factorization_records_user_added_once_and_reference_only_has_no_preference(tmp_path):
    service, row, _ = full(tmp_path)
    row = service.factorize(command(row), policy(), proposal=None, now=NOW)
    signals = service.repository.signals(row.candidate_id, row.domain)
    assert len(signals) == 1 and signals[0].kind == "user_added"
    assert signals[0].owner_preference == "like"
    assert signals[0].job.search_term is None
    assert row.feature_set_id and row.signal_id
    other, ref, _ = full(tmp_path / "other", job_preference=None, owner_text="", intent="inspect")
    ref = other.factorize(command(ref), policy(), proposal=None, now=NOW)
    assert ref.feature_set_id and not other.repository.signals(ref.candidate_id, ref.domain)


def test_invalid_model_output_uses_grounded_fallback(tmp_path):
    service, row, _ = full(tmp_path)
    row = service.factorize(
        command(row), policy(), proposal={"invalid": "PRIVATE_SENTINEL"}, now=NOW
    )
    assert row.feature_set_id and row.signal_id


def test_draft_can_progress_without_learning_and_review_is_bound_and_independent(tmp_path):
    service, row, snap = full(tmp_path)
    row = service.submit_draft(draft_payload(row), now=NOW)
    from jobagent.jobs.job_intake import next_actions

    assert "independent_review" in next_actions(row) and not row.feature_set_id
    data = command(
        row,
        draft_digest=row.draft_digest,
        snapshot_id=snap.snapshot_id,
        reviewer_reference="AUTHOR_RUN",
        review_reference="REVIEW_ONE",
        accepted=True,
    )
    with pytest.raises(ContractValidationError):
        service.review_draft(data, now=NOW)
    with pytest.raises(ContractValidationError):
        service.review_draft(
            {**data, "reviewer_reference": "OTHER_RUN", "draft_digest": "sha256:wrong"}, now=NOW
        )
    row = service.review_draft({**data, "reviewer_reference": "OTHER_RUN"}, now=NOW)
    assert row.review.accepted and "prepare_outreach_batch" in next_actions(row)


def test_no_canonical_evidence_or_hard_filter_bypass(tmp_path):
    service, row, _ = full(tmp_path)
    with pytest.raises(ContractValidationError):
        service.submit_draft(
            draft_payload(
                row,
                draft=dict(
                    job_id=row.job_id, platform="boss", text=TEXT, evidence_ids=["EVID_FAKE"]
                ),
            ),
            now=NOW,
        )
    with pytest.raises(ContractValidationError):
        service.submit_draft(
            draft_payload(
                row, filter_context=dict(candidate_id="CAND_DEMO", allowed_locations=["北京"])
            ),
            now=NOW,
        )


def test_changed_jd_invalidates_draft_features_and_plan(tmp_path):
    service, row, snap = full(tmp_path)
    row = service.factorize(command(row), policy(), proposal=None, now=NOW)
    row = service.submit_draft(draft_payload(row), now=NOW)
    from jobagent.schemas.jd_snapshot import JDSnapshotInput
    from jobagent.storage.jd_snapshot_repository import SqliteJDSnapshotRepository

    data = snap.model_dump(
        exclude={"snapshot_id", "snapshot_version", "jd_text_hash", "content_digest"}
    )
    data.update(
        observation_id="CHANGE",
        jd_text=snap.jd_text + "职责变化。",
        fetched_at=NOW + timedelta(days=1),
    )
    SqliteJDSnapshotRepository(service.database).capture(JDSnapshotInput.model_validate(data))
    row = service.synchronize(row.intake_id, row.candidate_id, now=NOW + timedelta(days=1))
    assert row.snapshot_id is None and row.feature_set_id is None and row.draft is None
    assert row.plan_id is None and row.blocked_reason == "jd_changed"


def test_interest_withdrawal_appends_neutral_without_rewriting_history(tmp_path):
    service, row, _ = full(tmp_path)
    row = service.factorize(command(row), policy(), proposal=None, now=NOW)
    row = service.set_interest(
        command(
            row, job_preference="neutral", owner_text="撤回方向偏好", message_reference="OWNER_TWO"
        ),
        now=NOW + timedelta(seconds=1),
    )
    signals = service.repository.signals(row.candidate_id, row.domain)
    assert [s.owner_preference for s in signals] == ["like", "neutral"]
    assert row.plan_id is None and row.signal_id == signals[-1].event_id


def test_existing_sent_job_routes_to_conversation_not_first_greeting(tmp_path):
    service, row, _ = full(tmp_path)
    from jobagent.storage.outreach_repository import SqliteOutreachRepository
    from tests.jobs.test_sent_tracking import outreach_records

    _, _, audit = outreach_records()
    audit = audit.model_copy(update={"job_id": row.job_id})
    SqliteOutreachRepository(service.database).append_audit(audit)
    row = service.synchronize(row.intake_id, row.candidate_id, now=NOW)
    from jobagent.jobs.job_intake import next_actions

    assert "continue_conversation" in next_actions(row)
    assert "generate_greeting" not in next_actions(row)
    with pytest.raises(ContractValidationError):
        service.submit_draft(draft_payload(row), now=NOW)


def test_control_requires_owner_to_resume_and_closed_never_reopens(tmp_path):
    service, row, _ = full(tmp_path)
    row = service.control(command(row, action="pause", reason="login_gate"), now=NOW)
    with pytest.raises(ContractValidationError):
        service.control(command(row, action="resume", reason="handled"), now=NOW)
    row = service.control(
        command(row, action="resume", reason="handled", owner_text="继续处理"), now=NOW
    )
    row = service.control(
        command(row, action="close", reason="owner_closed", owner_text="停止处理"), now=NOW
    )
    with pytest.raises(ContractValidationError):
        service.control(command(row, action="resume", reason="again", owner_text="继续"), now=NOW)


def test_merge_list_reference_with_existing_url_intake_preserves_both_messages(tmp_path):
    service, original, _ = full(tmp_path)
    original = service.factorize(command(original), policy(), proposal=None, now=NOW)
    from tests.storage.test_job_intake import request

    pending = service.repository.enqueue(
        request(
            request_id="REQ_LIST",
            entry_kind="list_item",
            job_url=None,
            target_reference="35",
            list_version="LIST_ONE",
            message_reference="MSG_LIST",
            job_preference=None,
        ),
        now=NOW,
    )
    service.save_selection(
        dict(
            candidate_id="CAND_DEMO",
            platform="boss",
            list_version="LIST_ONE",
            message_reference="MSG_LIST",
            observed_at=NOW,
            targets={"35": original.job_id},
        ),
        now=NOW,
    )
    merged = service.resolve(command(pending, job_id=original.job_id), now=NOW)
    assert merged.intake_id == original.intake_id
    assert len(merged.requests) == 2
    assert (
        service.repository.get(pending.intake_id, pending.candidate_id).merged_into
        == original.intake_id
    )
    assert len(service.repository.signals(original.candidate_id, original.domain)) == 1


def test_operation_replay_and_changed_payload_are_checked_before_cas(tmp_path):
    service, row, _ = full(tmp_path)
    operation = command(row)
    changed = service.factorize(operation, policy(), proposal=None, now=NOW)
    assert service.factorize(operation, policy(), proposal=None, now=NOW) == changed
    with pytest.raises(ContractValidationError):
        service.factorize(operation, policy(), proposal={"changed": True}, now=NOW)


def test_new_real_detail_evidence_unlocks_only_matching_full_snapshot(tmp_path):
    service, row, snap = setup(tmp_path)
    from jobagent.schemas.jd_snapshot import JDSnapshotInput
    from jobagent.schemas.sourcing import (
        SourcingAttemptRequest,
        SourcingResultRequest,
        SourcingRunRequest,
    )
    from jobagent.storage.jd_snapshot_repository import SqliteJDSnapshotRepository
    from jobagent.storage.job_repository import SqliteJobRepository
    from jobagent.storage.sourcing_repository import SqliteSourcingRepository

    meter = SqliteSourcingRepository(service.database)
    meter.start_run(
        SourcingRunRequest(run_id="RUN_OK", candidate_id=row.candidate_id, source="boss"),
        now=NOW,
        daily_cap=50,
    )
    meter.reserve(
        SourcingAttemptRequest(
            attempt_id="ATT_OK", run_id="RUN_OK", kind="detail", source_job_id="1", url=row.job_url
        ),
        now=NOW,
    )
    data = snap.model_dump(
        exclude={"snapshot_id", "snapshot_version", "jd_text_hash", "content_digest"}
    )
    data.update(
        observation_id="ACTUAL_NEW",
        jd_text=snap.jd_text + "职责有更新。",
        fetched_at=NOW + timedelta(seconds=1),
    )
    fresh = (
        SqliteJDSnapshotRepository(service.database)
        .capture(JDSnapshotInput.model_validate(data))
        .snapshot
    )
    job = service.job(row).model_copy(update={"jd_raw": fresh.jd_text})
    SqliteJobRepository(service.database).save_job(job)
    meter.complete(
        SourcingResultRequest(attempt_id="ATT_OK", outcome="complete"),
        now=NOW + timedelta(seconds=2),
    )
    current = service.attach_snapshot(
        command(row, snapshot_id=fresh.snapshot_id, attempt_id="ATT_OK"),
        now=NOW + timedelta(seconds=3),
    )
    assert current.snapshot_id == fresh.snapshot_id


def test_accepted_review_can_bind_existing_batch_without_granting_approval(tmp_path):
    service, row, snap = full(tmp_path)
    row = service.submit_draft(draft_payload(row), now=NOW)
    row = service.review_draft(
        command(
            row,
            draft_digest=row.draft_digest,
            snapshot_id=snap.snapshot_id,
            reviewer_reference="REVIEW_RUN",
            review_reference="REVIEW_DOC",
            accepted=True,
        ),
        now=NOW,
    )
    from jobagent.outreach.service import OutreachService

    batch = (
        OutreachService()
        .build_batch(
            [row.draft],
            jobs={row.job_id: service.job(row)},
            already_contacted=[],
            confirmed_evidence_ids=[],
            batch_id="OBATCH_INTAKE_TEST",
            created_at=NOW,
        )
        .batch
    )
    service.outreach.save_batch(batch)
    row = service.attach_batch(command(row, batch_id=batch.batch_id), now=NOW)
    assert row.batch_id == batch.batch_id
    assert service.outreach.get_approval(batch.batch_id) is None


def test_new_message_can_record_interest_without_redrafting_or_duplicate_count(tmp_path):
    service, row, _ = full(tmp_path, job_preference=None, owner_text="")
    row = service.factorize(command(row), policy(), proposal=None, now=NOW)
    row = service.submit_draft(draft_payload(row), now=NOW)
    newer = request(
        request_id="REQ_NEW_INTEREST",
        message_reference="MSG_NEW",
        job_url=str(row.job_url),
        target_reference=str(row.job_url),
        occurred_at=NOW + timedelta(seconds=1),
    )
    row = service.enqueue(newer, now=NOW + timedelta(seconds=1))
    assert row.signal_id and row.draft is not None and row.feature_set_id
    assert len(service.repository.signals(row.candidate_id, row.domain)) == 1


def test_number_resolution_requires_persisted_list_mapping_not_arbitrary_job_id(tmp_path):
    service, original, _ = full(tmp_path)
    pending = service.repository.enqueue(
        request(
            request_id="REQ_SELECT",
            entry_kind="list_item",
            job_url=None,
            target_reference="35",
            list_version="LIST_PROOF",
            message_reference="MSG_SELECT",
            job_preference=None,
        ),
        now=NOW,
    )
    with pytest.raises(ContractValidationError):
        service.resolve(command(pending, job_id=original.job_id), now=NOW)
    evidence = dict(
        candidate_id="CAND_DEMO",
        platform="boss",
        list_version="LIST_PROOF",
        message_reference="MSG_SELECT",
        observed_at=NOW,
        targets={"35": original.job_id},
    )
    service.save_selection(evidence, now=NOW)
    assert (
        service.resolve(command(pending, job_id=original.job_id), now=NOW).intake_id
        == original.intake_id
    )
    with pytest.raises(ContractValidationError):
        service.save_selection({**evidence, "targets": {"36": original.job_id}}, now=NOW)


def test_known_weak_match_cannot_silently_pass_the_new_draft_route(tmp_path, monkeypatch):
    service, row, _ = full(tmp_path)
    monkeypatch.setattr(
        service.jobs, "latest_match_tiers", lambda *args: {row.job_id: "weak_match"}
    )
    with pytest.raises(ContractValidationError):
        service.submit_draft(draft_payload(row), now=NOW)


def test_recovery_after_enqueue_commit_restores_missing_interest_signal(tmp_path):
    service, row, _ = full(tmp_path, job_preference=None, owner_text="")
    row = service.factorize(command(row), policy(), proposal=None, now=NOW)
    # Emulate a crash between the durable incoming message and signal attachment.
    incoming = request(
        request_id="REQ_CRASH",
        message_reference="MSG_CRASH",
        job_url=str(row.job_url),
        target_reference=str(row.job_url),
        occurred_at=NOW + timedelta(seconds=1),
    )
    row = service.repository.enqueue(incoming, now=NOW + timedelta(seconds=1))
    assert row.signal_id is None
    recovered = service.synchronize(row.intake_id, row.candidate_id, now=NOW + timedelta(seconds=2))
    assert recovered.signal_id
    assert len(service.repository.signals(row.candidate_id, row.domain)) == 1


def test_old_message_arriving_late_does_not_undo_newer_owner_choice(tmp_path):
    service, row, _ = full(tmp_path)
    row = service.factorize(command(row), policy(), proposal=None, now=NOW)
    row = service.set_interest(
        command(
            row, job_preference="neutral", owner_text="撤回偏好", message_reference="MSG_NEUTRAL"
        ),
        now=NOW + timedelta(seconds=2),
    )
    older = request(
        request_id="REQ_OLDER",
        message_reference="MSG_OLDER",
        job_url=str(row.job_url),
        target_reference=str(row.job_url),
        occurred_at=NOW + timedelta(seconds=1),
    )
    row = service.enqueue(older, now=NOW + timedelta(seconds=3))
    signals = service.repository.signals(row.candidate_id, row.domain)
    assert next(s for s in signals if s.event_id == row.signal_id).owner_preference == "neutral"


def test_batch_reference_must_bind_current_item_digest_not_only_same_words(tmp_path):
    service, row, snap = full(tmp_path)
    row = service.submit_draft(draft_payload(row), now=NOW)
    row = service.review_draft(
        command(
            row,
            draft_digest=row.draft_digest,
            snapshot_id=snap.snapshot_id,
            reviewer_reference="REVIEW_RUN",
            review_reference="REVIEW_DOC",
            accepted=True,
        ),
        now=NOW,
    )
    from jobagent.outreach.service import OutreachService

    batch = (
        OutreachService()
        .build_batch(
            [row.draft],
            jobs={row.job_id: service.job(row)},
            already_contacted=[],
            confirmed_evidence_ids=[],
            batch_id="OBATCH_STALE",
            created_at=NOW,
        )
        .batch
    )
    batch = batch.model_copy(
        update={
            "items": [
                batch.items[0].model_copy(update={"item_digest": "sha256:old-job-content"}),
            ]
        }
    )
    service.outreach.save_batch(batch)
    with pytest.raises(ContractValidationError):
        service.attach_batch(command(row, batch_id=batch.batch_id), now=NOW)


def test_brand_new_url_can_resolve_from_listing_without_fabricating_jd(tmp_path):
    from jobagent.jobs.jd_snapshot import capture_from_record
    from jobagent.jobs.job_intake import next_actions
    from jobagent.jobs.normalization import JobNormalizer
    from jobagent.schemas.job_intelligence import JobListing, SourceJobRecord
    from jobagent.schemas.sourcing import (
        SourcingAttemptRequest,
        SourcingResultRequest,
        SourcingRunRequest,
    )
    from jobagent.storage.job_intake_service import JobIntakeService
    from jobagent.storage.sourcing_repository import SqliteSourcingRepository
    from tests.storage.test_job_intake import repository, request

    repo = repository(tmp_path)
    service = JobIntakeService(repo.database)
    row = service.enqueue(request(), now=NOW)
    listing = JobListing(
        source="boss",
        source_job_id="brand-new",
        title="品牌设计师",
        company="合成新公司",
        url=row.job_url,
        collected_at=NOW,
    )
    row = service.resolve(command(row, listing=listing.model_dump()), now=NOW)
    assert row.job_id is None and row.listing.source_job_id == "brand-new"
    assert next_actions(row) == ["fetch_full_jd"]
    assert service.jobs.list_jobs() == []
    meter = SqliteSourcingRepository(repo.database)
    meter.start_run(
        SourcingRunRequest(run_id="RUN_NEW", source="boss", candidate_id=row.candidate_id),
        now=NOW,
        daily_cap=50,
    )
    meter.reserve(
        SourcingAttemptRequest(
            attempt_id="ATT_NEW",
            run_id="RUN_NEW",
            kind="detail",
            source_job_id="brand-new",
            url=row.job_url,
        ),
        now=NOW,
    )
    raw = SourceJobRecord(
        source="boss",
        source_job_id="brand-new",
        title=listing.title,
        company=listing.company,
        location="上海",
        url=row.job_url,
        jd_raw="品牌设计师负责品牌与Figma设计交付及用户研究。",
        collected_at=NOW + timedelta(seconds=1),
    )
    job = JobNormalizer().normalize(raw)
    service.jobs.save_job(job)
    snapshot = service.knowledge.capture(capture_from_record(raw, job.id)).snapshot
    meter.complete(
        SourcingResultRequest(attempt_id="ATT_NEW", outcome="complete"),
        now=NOW + timedelta(seconds=2),
    )
    row = service.attach_snapshot(
        command(row, snapshot_id=snapshot.snapshot_id, attempt_id="ATT_NEW"),
        now=NOW + timedelta(seconds=3),
    )
    assert row.job_id == job.id and row.snapshot_id == snapshot.snapshot_id
    row = service.factorize(command(row), policy(), proposal=None, now=NOW + timedelta(seconds=4))
    assert row.feature_set_id and row.signal_id


def test_numbered_new_listing_is_bound_before_full_jd_exists(tmp_path):
    from jobagent.schemas.job_intelligence import JobListing
    from jobagent.storage.job_intake_service import JobIntakeService
    from tests.storage.test_job_intake import repository, request

    service = JobIntakeService(repository(tmp_path).database)
    row = service.enqueue(
        request(
            entry_kind="list_item", job_url=None, target_reference="35", list_version="NEW_LIST"
        ),
        now=NOW,
    )
    listing = JobListing(
        source="boss",
        source_job_id="new-list",
        title="设计师",
        company="合成新公司",
        url="https://example.com/new-list",
        collected_at=NOW,
    )
    service.save_selection(
        dict(
            candidate_id=row.candidate_id,
            platform="boss",
            list_version="NEW_LIST",
            message_reference="CHAT_MSG_ONE",
            observed_at=NOW,
            targets={"35": listing.model_dump()},
        ),
        now=NOW,
    )
    row = service.resolve(command(row, listing=listing.model_dump()), now=NOW)
    assert row.listing.source_job_id == "new-list" and row.snapshot_id is None


def test_new_url_and_card_merge_before_either_has_jd(tmp_path):
    from jobagent.schemas.job_intelligence import JobListing
    from jobagent.storage.job_intake_service import JobIntakeService

    service = JobIntakeService(repository(tmp_path).database)
    first = service.enqueue(request(), now=NOW)
    listing = JobListing(
        source="boss",
        source_job_id="unread",
        title="设计师",
        company="合成公司",
        url=first.job_url,
        collected_at=NOW,
    )
    first = service.resolve(command(first, listing=listing.model_dump()), now=NOW)
    card = service.enqueue(
        request(
            request_id="REQ_CARD_NEW",
            entry_kind="conversation_card",
            job_url=None,
            target_reference="CARD_KEY",
            message_reference="CARD_MESSAGE",
            job_preference=None,
        ),
        now=NOW,
    )
    service.save_selection(
        dict(
            candidate_id=card.candidate_id,
            platform="boss",
            list_version="CARD_MESSAGE",
            message_reference="CARD_MESSAGE",
            observed_at=NOW,
            targets={"CARD_KEY": listing.model_dump()},
        ),
        now=NOW,
    )
    merged = service.resolve(command(card, listing=listing.model_dump()), now=NOW)
    assert merged.intake_id == first.intake_id and merged.job_id is None
    assert len(merged.requests) == 2
