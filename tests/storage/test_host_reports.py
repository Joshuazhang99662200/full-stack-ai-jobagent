from datetime import timedelta

import pytest

from jobagent.errors import ContractValidationError
from tests.storage.test_intake_strategy import add, data, strategy
from tests.storage.test_job_intake import NOW


def round_evidence(tmp_path, number=1, *, search=True):
    from jobagent.schemas.jd_snapshot import JDSnapshotInput
    from jobagent.schemas.sourcing import SourcingAttemptRequest, SourcingResultRequest
    from jobagent.storage.host_checks import HostPageService
    from jobagent.storage.host_reports import HostRoundReporter

    if number == 1:
        service, first = add(tmp_path, 1)
        service, _ = add(tmp_path, 2)
    else:
        from jobagent.storage.database import Database
        from jobagent.storage.job_intake_service import JobIntakeService

        service = JobIntakeService(Database(tmp_path / "private.sqlite3"))
        first = service.repository.list_records("CAND_DEMO", "design")[0]
    start = NOW + timedelta(hours=number)
    engine = strategy(service)
    engine.rebuild(
        data(),
        __import__("tests.storage.test_job_intake_service", fromlist=["policy"]).policy(),
        now=start,
    )
    from jobagent.schemas.sourcing import SourcingRunRequest
    from jobagent.storage.sourcing_repository import SqliteSourcingRepository

    meter = SqliteSourcingRepository(service.database)
    run_id = f"RUN_REPORT_{number}"
    meter.start_run(
        SourcingRunRequest(run_id=run_id, candidate_id="CAND_DEMO", source="boss"),
        now=start,
        daily_cap=50,
    )
    claim = dict(candidate_id="CAND_DEMO", domain="design", run_id=run_id)
    bound = engine.claim(claim, now=start)
    query = bound["plan"]["ordered_queries"][0]["query"]
    meter.reserve(
        SourcingAttemptRequest(
            attempt_id=f"QUERY_REPORT_{number}", run_id=run_id, kind="query", search_term=query
        ),
        now=start,
    )
    meter.complete(
        SourcingResultRequest(
            attempt_id=f"QUERY_REPORT_{number}", outcome="complete", listing_count=2
        ),
        now=start + timedelta(seconds=1),
    )
    engine.record_search(
        {**claim, "attempt_id": f"QUERY_REPORT_{number}", "new_count": 0},
        now=start + timedelta(seconds=1),
    )
    snapshot = service.knowledge.get(first.snapshot_id)
    capture = snapshot.model_dump(
        exclude={"snapshot_id", "snapshot_version", "jd_text_hash", "content_digest"}
    )
    capture.update(
        observation_id=f"ROUND_SEARCH_{number}",
        discovery_kind="search" if search else "unknown",
        query_hit=query if search else None,
        fetched_at=start + timedelta(seconds=1),
    )
    service.knowledge.capture(JDSnapshotInput.model_validate(capture))
    capture.update(observation_id=f"ROUND_MANUAL_{number}", discovery_kind="manual", query_hit=None)
    service.knowledge.capture(JDSnapshotInput.model_validate(capture))
    pages = HostPageService(service.database)
    for surface in ("messages", "search"):
        pages.record(
            dict(
                observation_id=f"PAGE_{number}_{surface}",
                candidate_id="CAND_DEMO",
                source="boss",
                surface=surface,
                state="logged_in",
                observed_at=start + timedelta(seconds=1),
                evidence_reference=f"SCREEN_{number}_{surface}",
            ),
            now=start + timedelta(seconds=1),
        )
    payload = dict(
        report_id=f"ROUND_{number}",
        candidate_id="CAND_DEMO",
        domain="design",
        run_ids=[run_id],
        started_at=start,
        completed_at=start + timedelta(minutes=1),
        search_observation_ids=[f"ROUND_SEARCH_{number}"],
        manual_observation_ids=[f"ROUND_MANUAL_{number}"],
        dedup_count=1,
        filter_reasons={"salary": 0},
        metrics_evidence_reference=f"METRICS_{number}",
        unfinished=[],
        evidence_mode="synthetic",
    )
    return HostRoundReporter(service.database), service, payload


def test_report_derives_real_executions_and_excludes_manual_from_query_denominator(tmp_path):
    reporter, _, payload = round_evidence(tmp_path)
    report = reporter.record(payload, now=payload["completed_at"])
    assert report["query_attribution"]["ratio"] == 1.0
    assert report["query_attribution"]["search_samples"] == 1
    assert report["query_attribution"]["manual_samples"] == 1
    assert len(report["executed_queries"]) == 1 and report["new_jobs"] == 0
    assert report["dedup_count"] == 1 and report["filter_reasons"] == {"salary": 0}
    assert report["new_drafts"] == 0 and report["lexicon_versions"]
    assert report["login_states"]["boss/messages"]["state"] == "logged_in"
    assert "newly_closed" in report["tracking"]
    assert report["real_browser_verified"] is False
    assert reporter.record(payload, now=payload["completed_at"]) == report
    with pytest.raises(ContractValidationError):
        reporter.record({**payload, "dedup_count": 2}, now=payload["completed_at"])


def test_missing_query_hit_is_reported_not_invented(tmp_path):
    reporter, _, payload = round_evidence(tmp_path, search=False)
    result = reporter.record(payload, now=payload["completed_at"])
    assert result["query_attribution"]["ratio"] == 0.0
    assert result["query_attribution"]["unattributed"] == ["ROUND_SEARCH_1"]
    assert not result["core_checks_passed"]


def test_zero_samples_and_absent_host_counters_cannot_claim_full_acceptance(tmp_path):
    reporter, service, payload = round_evidence(tmp_path)
    with service.database.connect() as connection, connection:
        connection.execute(
            "DELETE FROM jd_discoveries WHERE observation_id = ?", ("ROUND_SEARCH_1",)
        )
    payload.update(
        search_observation_ids=[],
        dedup_count=None,
        filter_reasons=None,
        metrics_evidence_reference=None,
    )
    result = reporter.record(payload, now=payload["completed_at"])
    assert result["query_attribution"]["ratio"] is None
    assert not result["core_checks_passed"]
    assert result["dedup_count"] is None


def test_two_round_check_distinguishes_core_evidence_from_real_host_verification(tmp_path):
    first, _, payload1 = round_evidence(tmp_path, 1)
    first.record(payload1, now=payload1["completed_at"])
    second, _, payload2 = round_evidence(tmp_path, 2)
    second.record(payload2, now=payload2["completed_at"])
    result = second.verify_two(
        dict(candidate_id="CAND_DEMO", first_report_id="ROUND_1", second_report_id="ROUND_2")
    )
    assert result["core_checks_passed"] and not result["real_browser_verified"]
    with pytest.raises(ContractValidationError):
        second.verify_two(
            dict(candidate_id="CAND_OTHER", first_report_id="ROUND_1", second_report_id="ROUND_2")
        )


def test_omitting_bad_search_discoveries_cannot_fake_perfect_attribution(tmp_path):
    reporter, _, payload = round_evidence(tmp_path, search=False)
    payload["search_observation_ids"] = []
    result = reporter.record(payload, now=payload["completed_at"])
    assert result["query_attribution"]["ratio"] == 0.0
    assert result["query_attribution"]["search_samples"] == 1
    assert "ROUND_SEARCH_1" in result["query_attribution"]["unattributed"]


def test_round_tracking_summary_uses_state_at_completion_not_later_events(tmp_path):
    reporter, service, payload = round_evidence(tmp_path)
    from jobagent.storage.sent_tracking_repository import SqliteSentTrackingRepository
    from tests.jobs.test_sent_tracking import event, proof

    tracking = SqliteSentTrackingRepository(service.database)
    state = tracking.start(
        proof(),
        candidate_id="CAND_DEMO",
        tracking_id="TRACK_HISTORY",
        now=payload["started_at"],
        next_poll_at=payload["started_at"] + timedelta(hours=4),
    )
    later = payload["completed_at"] + timedelta(hours=1)
    tracking.apply(
        event(
            state,
            "user_abandon",
            observed_at=later,
            evidence_kind="owner_message",
            owner_text="停止跟踪",
        ),
        now=later,
    )
    report = reporter.record(payload, now=later)
    assert report["tracking"]["counts"] == {"awaiting_reply": 1}
    assert report["tracking"]["newly_closed"] == 0


def test_detail_attempt_report_uses_completed_results_not_planned_capacity(tmp_path):
    from jobagent.schemas.sourcing import SourcingAttemptRequest, SourcingResultRequest
    from jobagent.storage.sourcing_repository import SqliteSourcingRepository

    reporter, service, payload = round_evidence(tmp_path)
    meter = SqliteSourcingRepository(service.database)
    meter.reserve(
        SourcingAttemptRequest(
            attempt_id="DETAIL_REPORT",
            run_id="RUN_REPORT_1",
            kind="detail",
            source_job_id="1",
            url="https://example.com/jobs/1",
        ),
        now=payload["started_at"] + timedelta(seconds=2),
    )
    meter.complete(
        SourcingResultRequest(attempt_id="DETAIL_REPORT", outcome="partial"),
        now=payload["started_at"] + timedelta(seconds=3),
    )
    result = reporter.record(payload, now=payload["completed_at"])
    assert result["detail_reads"] == {
        "attempts": 1,
        "complete": 0,
        "partial": 1,
        "failed": 0,
        "pending": 0,
    }


def pipeline_report_record(service, payload, number=1, *, at=None):
    from jobagent.jobs.jd_snapshot import text_digest
    from jobagent.schemas.pipeline import PipelineMeta
    from jobagent.storage.pipeline_repository import PipelineRepository
    from tests.jobs.test_pipeline_contracts import row

    created = at or payload["started_at"] + timedelta(seconds=2)
    job = row(
        pipeline_id=f"PIPE_{number:016X}",
        job_id=f"boss-pipeline-{number}",
        entered_at=created,
        state_changed_at=created,
        updated_at=created,
        draft_greeting="Synthetic draft",
        draft_version="SYNTHETIC_V1",
        draft_digest=text_digest("Synthetic draft"),
    )
    meta = PipelineMeta(
        pipeline_id=job.pipeline_id,
        entered_evidence_reference="SYNTHETIC_ENTRY",
        normalized_job_id=f"JOB_DEMO_{number}",
        domain="design",
    )
    store = PipelineRepository(service.database)
    pair = store.create(
        job, meta, event_id=f"REPORT_CREATE_{number}", evidence_reference="SYNTHETIC_ENTRY"
    )
    return store, pair


def send_pipeline(store, pair, at):
    from jobagent.schemas.pipeline import PipelineTransition, PipelineVerifiedEvidence

    job, meta = pair
    event = PipelineTransition(
        event_id="REPORT_SEND",
        pipeline_id=job.pipeline_id,
        candidate_id=job.candidate_id,
        expected_version=meta.version,
        from_state="draft_pending",
        to_state="greeting_sent",
        changed_at=at,
        evidence_kind="send_audit",
        evidence_reference="SYNTHETIC_SENT_AUDIT",
        send_reference="SYNTHETIC_SENT_AUDIT",
        reason_code="normal",
    )
    proof = PipelineVerifiedEvidence(
        reference=event.evidence_reference,
        kind="send_audit",
        observed_at=at,
        source_at=at,
        sent_text=job.draft_greeting,
        sent_at=at,
        send_reference=event.send_reference,
    )
    return store.transition(event, proof, now=at)


def test_authority_report_uses_pipeline_snapshots_at_completion_not_legacy_or_later_state(tmp_path):
    from jobagent.schemas.pipeline import PipelineTransition, PipelineVerifiedEvidence
    from jobagent.storage.sent_tracking_repository import SqliteSentTrackingRepository
    from tests.jobs.test_sent_tracking import proof

    reporter, service, payload = round_evidence(tmp_path)
    legacy = SqliteSentTrackingRepository(service.database)
    legacy.start(
        proof(),
        candidate_id="CAND_DEMO",
        tracking_id="ARCHIVED_TRACKING",
        now=payload["started_at"],
        next_poll_at=payload["started_at"] + timedelta(hours=4),
    )
    store, pair = pipeline_report_record(service, payload)
    job, meta = send_pipeline(store, pair, payload["started_at"] + timedelta(seconds=3))
    later = payload["completed_at"] + timedelta(hours=1)
    event = PipelineTransition(
        event_id="AFTER_REPORT_CLOSURE",
        pipeline_id=job.pipeline_id,
        candidate_id=job.candidate_id,
        expected_version=meta.version,
        from_state="greeting_sent",
        to_state="abandoned",
        changed_at=later,
        evidence_kind="owner_message",
        evidence_reference="LATER_OWNER_REPLY",
        reason_code="user_abandoned",
    )
    proof = PipelineVerifiedEvidence(
        reference=event.evidence_reference,
        kind=event.evidence_kind,
        observed_at=later,
        source_at=later,
        owner_decision=True,
    )
    store.transition(event, proof, now=later)
    result = reporter.record(payload, now=later)
    assert result["tracking"]["state_authority"] == "pipeline_jobs"
    assert result["tracking"]["counts"]["greeting_sent"] == 1
    assert result["tracking"]["counts"]["abandoned"] == 0
    assert "awaiting_reply" not in result["tracking"]["counts"]
    assert result["tracking"]["newly_closed"] == 0
    assert result["pipeline"] == result["tracking"]
    assert result["tracking"]["next_checks"][0]["next_check_at"] is None
    assert result["tracking"]["next_checks"][0]["deadline_at"]
    assert result["partial_not_in_strategy"] == [job.pipeline_id]


def test_pipeline_report_counts_unproven_legacy_snapshot_without_fabricating_check_times(tmp_path):
    from jobagent.jobs.jd_snapshot import canonical_digest
    from jobagent.schemas.pipeline import PipelineHistory

    reporter, service, payload = round_evidence(tmp_path)
    store, (job, meta) = pipeline_report_record(service, payload)
    at = payload["started_at"] + timedelta(seconds=3)
    declared = job.model_copy(
        update={"pipeline_state": "greeting_sent", "state_changed_at": at, "updated_at": at}
    )
    metadata = meta.model_copy(update={"version": 2, "proof_status": "proof_pending"})
    with service.database.connect() as connection, connection:
        store.write_job(connection, declared, metadata)
        store.append_history(
            connection,
            PipelineHistory(
                history_id="PH_DECLARED",
                pipeline_id=job.pipeline_id,
                from_state="draft_pending",
                to_state="greeting_sent",
                changed_at=at,
                evidence_kind="platform_state",
                evidence_reference="PRIVATE_LEGACY",
                reason_code="normal",
            ),
        )
        store.remember(connection, "DECLARED", canonical_digest("DECLARED"), (declared, metadata))
    result = reporter.record(payload, now=payload["completed_at"])
    assert result["tracking"]["proof_pending"] == 1
    assert result["tracking"]["counts"]["greeting_sent"] == 1
    detail = result["tracking"]["next_checks"][0]
    assert detail["deadline_at"] is None and detail["next_check_at"] is None
    assert detail["proof_status"] == "proof_pending"


def test_missing_immutable_pipeline_snapshot_is_reported_unverified_not_guessed(tmp_path):
    from jobagent.schemas.pipeline import PipelineHistory

    reporter, service, payload = round_evidence(tmp_path)
    store, (job, meta) = pipeline_report_record(service, payload)
    at = payload["started_at"] + timedelta(seconds=3)
    declared = job.model_copy(
        update={"pipeline_state": "greeting_sent", "state_changed_at": at, "updated_at": at}
    )
    metadata = meta.model_copy(update={"version": 2, "proof_status": "proof_pending"})
    with service.database.connect() as connection, connection:
        store.write_job(connection, declared, metadata)
        store.append_history(
            connection,
            PipelineHistory(
                history_id="PH_MISSING_SNAPSHOT",
                pipeline_id=job.pipeline_id,
                from_state="draft_pending",
                to_state="greeting_sent",
                changed_at=at,
                evidence_kind="platform_state",
                evidence_reference="PRIVATE_LEGACY",
                reason_code="normal",
            ),
        )
    result = reporter.record(payload, now=payload["completed_at"])
    assert result["tracking"]["unverified_pipeline_ids"] == [job.pipeline_id]
    assert sum(result["tracking"]["counts"].values()) == 0
    assert result["tracking"]["as_of_verification"] == "incomplete_snapshot_history"


def test_later_authority_activation_does_not_replace_an_older_legacy_report(tmp_path):
    from jobagent.storage.sent_tracking_repository import SqliteSentTrackingRepository
    from tests.jobs.test_sent_tracking import proof

    reporter, service, payload = round_evidence(tmp_path)
    tracking = SqliteSentTrackingRepository(service.database)
    tracking.start(
        proof(),
        candidate_id="CAND_DEMO",
        tracking_id="EARLY_TRACKING",
        now=payload["started_at"],
        next_poll_at=payload["started_at"] + timedelta(hours=4),
    )
    later = payload["completed_at"] + timedelta(hours=1)
    pipeline_report_record(service, payload, at=later)
    result = reporter.record(payload, now=later)
    assert result["tracking"]["counts"] == {"awaiting_reply": 1}
    assert result.get("pipeline") is None


def test_same_timestamp_transitions_use_append_order_in_as_of_snapshot_validation(tmp_path):
    reporter, service, payload = round_evidence(tmp_path)
    store, pair = pipeline_report_record(service, payload)
    send_pipeline(store, pair, pair[0].entered_at)
    result = reporter.record(payload, now=payload["completed_at"])
    assert result["tracking"]["unverified_pipeline_ids"] == []
    assert result["tracking"]["counts"]["greeting_sent"] == 1


def test_actual_host_next_poll_is_distinct_from_silence_deadline(tmp_path):
    reporter, service, payload = round_evidence(tmp_path)
    store, pair = pipeline_report_record(service, payload)
    send_pipeline(store, pair, pair[0].entered_at + timedelta(seconds=1))
    payload["next_poll_at"] = payload["completed_at"] + timedelta(hours=4)
    result = reporter.record(payload, now=payload["completed_at"])
    check = result["tracking"]["next_checks"][0]
    assert check["next_check_at"] == payload["next_poll_at"].isoformat()
    assert check["deadline_at"] != check["next_check_at"]
    assert check["schedule_verification"] == "host_observed_only"
