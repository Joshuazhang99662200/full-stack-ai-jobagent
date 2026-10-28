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
        proof(), candidate_id="CAND_DEMO", tracking_id="TRACK_HISTORY", now=payload["started_at"]
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
