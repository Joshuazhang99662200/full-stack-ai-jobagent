import sqlite3
from datetime import timedelta

import pytest

from jobagent.errors import ContractValidationError
from jobagent.schemas.pipeline import PipelineTransition, PipelineVerifiedEvidence
from tests.storage.test_job_intake_service import NOW, command, draft_payload, policy, setup


def prepared(tmp_path, number=1, *, at=NOW):
    from jobagent.storage.pipeline_service import PipelineService

    core, intake, snapshot = setup(tmp_path, number=number)
    intake = core.attach_snapshot(command(intake, snapshot_id=snapshot.snapshot_id), now=NOW)
    intake = core.factorize(command(intake), policy(), proposal=None, now=NOW)
    intake = core.submit_draft(draft_payload(intake), now=NOW)
    pipeline = PipelineService(core.database)
    pair = pipeline.create(
        dict(
            event_id=f"CREATE_METRIC_{number}",
            candidate_id="CAND_DEMO",
            normalized_job_id=intake.job_id,
            intake_id=intake.intake_id,
            evidence_reference=f"PRIVATE_ENTRY_{number}",
            salary_minimum_k=18,
        ),
        now=at,
    )
    return pipeline, pair


def transition(pipeline, pair, target, *, at, number=1):
    job, meta = pair
    event = PipelineTransition(
        event_id=f"EVENT_METRIC_{number}_{target}",
        pipeline_id=job.pipeline_id,
        candidate_id=job.candidate_id,
        expected_version=meta.version,
        from_state=job.pipeline_state,
        to_state=target,
        changed_at=at,
        evidence_kind="send_audit" if target == "greeting_sent" else "conversation_message",
        evidence_reference=f"PRIVATE_{number}_{target}",
        reason_code="normal",
        send_reference=f"AUDIT_METRIC_{number}" if target == "greeting_sent" else None,
    )
    proof = PipelineVerifiedEvidence(
        reference=event.evidence_reference,
        kind=event.evidence_kind,
        observed_at=at,
        source_at=at,
        read_confirmed=target == "greeting_read",
        substantive_reply=target == "initial_contact",
        sent_text=job.draft_greeting if target == "greeting_sent" else None,
        sent_at=at if target == "greeting_sent" else None,
        send_reference=event.send_reference,
        greeting_version="HVER_SYNTHETICV1" if target == "greeting_sent" else None,
    )
    return pipeline.repository.transition(event, proof, now=at)


def scope(pair):
    _job, meta = pair
    return dict(
        dimension_platform="boss",
        dimension_domain="design",
        dimension_scenario=None,
        dimension_tech="Figma",
        dimension_greeting_version=meta.sent_greeting_version,
        dimension_resume_version=None,
        dimension_salary_band=None,
    )


def selected(result, source="greeting_sent", target="greeting_read"):
    return next(
        m for m in result["metrics"] if (m["stage_from"], m["stage_to"]) == (source, target)
    )


def service(database):
    from jobagent.storage.pipeline_metrics import PipelineMetricsService

    return PipelineMetricsService(database)


def compute_input(pair, start=NOW, end=NOW + timedelta(hours=1)):
    return dict(candidate_id="CAND_DEMO", window_start=start, window_end=end, scope=scope(pair))


def test_stored_metrics_use_pipeline_history_and_validated_feature_provenance(tmp_path):
    pipeline, pair = prepared(tmp_path)
    pair = transition(pipeline, pair, "greeting_sent", at=NOW + timedelta(seconds=1))
    pair = transition(pipeline, pair, "greeting_read", at=NOW + timedelta(seconds=3))
    metrics = service(pipeline.database)
    request = compute_input(pair, start=NOW + timedelta(seconds=2))
    result = metrics.compute(request, now=NOW + timedelta(hours=1))
    item = selected(result)
    assert item["historical_rate"] == "0" and item["sliced_cumulative_rate"] == "1"
    assert item["window_rate"] is None
    assert metrics.compute(request, now=NOW + timedelta(hours=2)) == result
    assert len(metrics.facts("CAND_DEMO")) == 1
    assert metrics.get_metric(item["metric_id"], "CAND_DEMO").denominator == 1
    with pytest.raises(ContractValidationError):
        metrics.get_metric(item["metric_id"], "CAND_OTHER")
    with pipeline.database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM pipeline_stage_metrics").fetchone()[0] == 9
        fields = {r[1] for r in connection.execute("PRAGMA table_info(pipeline_stage_metrics)")}
        assert "candidate_id" not in fields
        assert (
            connection.execute(
                "SELECT candidate_id FROM pipeline_metric_context LIMIT 1"
            ).fetchone()[0]
            == "CAND_DEMO"
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM pipeline_stage_metrics")


def test_compute_rejects_caller_supplied_confirmation_and_unpersisted_feature_tags(tmp_path):
    pipeline, pair = prepared(tmp_path)
    metrics = service(pipeline.database)
    request = compute_input(pair)
    with pytest.raises(ContractValidationError):
        metrics.compute(
            {**request, "rule": {"rule_id": "FAKE_CONFIRMED"}}, now=NOW + timedelta(hours=1)
        )
    job, meta = pair
    forged = meta.model_copy(update={"tech": ["INVENTED_TAG"]})
    with pipeline.database.connect() as connection, connection:
        connection.execute(
            "UPDATE pipeline_meta SET meta_json = ? WHERE pipeline_id = ?",
            (forged.model_dump_json(), job.pipeline_id),
        )
    with pytest.raises(ContractValidationError):
        metrics.compute(
            {**request, "scope": {**scope(pair), "dimension_tech": "INVENTED_TAG"}},
            now=NOW + timedelta(hours=1),
        )


def test_diagnosis_accepts_only_stored_candidate_scoped_metric_ids_and_keeps_observations(tmp_path):
    pipeline, pair = prepared(tmp_path)
    metrics = service(pipeline.database)
    result = metrics.compute(compute_input(pair), now=NOW + timedelta(hours=1))
    ids = [m["metric_id"] for m in result["metrics"]]
    request = dict(candidate_id="CAND_DEMO", current_metric_ids=ids)
    report = metrics.diagnose(request, now=NOW + timedelta(hours=1))
    assert report["diagnoses"] == [] and report["report_id"]
    assert metrics.diagnose(request, now=NOW + timedelta(hours=2)) == report
    with pytest.raises(ContractValidationError):
        metrics.diagnose({**request, "candidate_id": "CAND_OTHER"}, now=NOW + timedelta(hours=1))
    with pytest.raises(ContractValidationError):
        metrics.diagnose({**request, "historical_rate": "0.1"}, now=NOW + timedelta(hours=1))
    with pytest.raises(ContractValidationError):
        metrics.diagnose({**request, "exclusions_reviewed": True}, now=NOW + timedelta(hours=1))
    with pipeline.database.connect() as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM pipeline_diagnosis_reports").fetchone()[0] == 1
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM pipeline_diagnosis_reports")


def test_fresh_evidence_recomputes_actual_sources_without_writing_or_trusting_rates(tmp_path):
    from jobagent.storage.host_migration import database_digest

    pipeline, pair = prepared(tmp_path)
    metrics = service(pipeline.database)
    result = metrics.compute(compute_input(pair), now=NOW + timedelta(hours=1))
    item = selected(result, "draft_pending", "greeting_sent")
    proof = metrics.get_evidence(item["metric_id"], "CAND_DEMO")
    before = database_digest(pipeline.database.path)
    assert (
        metrics.fresh_evidence(
            item["metric_id"], "CAND_DEMO", now=NOW + timedelta(hours=1)
        ).source_digest
        == proof.source_digest
    )
    assert database_digest(pipeline.database.path) == before
    prepared(tmp_path, number=2)
    fresh = metrics.fresh_evidence(item["metric_id"], "CAND_DEMO", now=NOW + timedelta(hours=1))
    assert fresh.source_digest != proof.source_digest


def test_historical_send_slice_is_frozen_from_its_actual_provenance_snapshot(tmp_path):
    pipeline, pair = prepared(tmp_path)
    pair = transition(pipeline, pair, "greeting_sent", at=NOW + timedelta(seconds=1))
    job, meta = pair
    with pipeline.database.connect() as connection, connection:
        changed = meta.model_copy(
            update={"feature_set_id": None, "snapshot_id": None, "tech": [], "scenario": []}
        )
        connection.execute(
            "UPDATE pipeline_meta SET meta_json=? WHERE pipeline_id=?",
            (changed.model_dump_json(), job.pipeline_id),
        )
    facts = service(pipeline.database).facts("CAND_DEMO")
    assert facts[0].dimension_tech == "Figma" and facts[0].dimension_domain == "design"


def test_two_real_cumulative_windows_append_diagnosis_and_linked_metric_copy(tmp_path):
    pipeline = None
    for n, day, read in [
        (1, 0, True),
        (2, 1, False),
        (3, 1, False),
        (4, 1, True),
        (5, 2, False),
        (6, 2, False),
    ]:
        at = NOW + timedelta(days=day, hours=1)
        pipeline, pair = prepared(tmp_path, number=n, at=at)
        pair = transition(pipeline, pair, "greeting_sent", at=at + timedelta(seconds=1), number=n)
        if read:
            pair = transition(
                pipeline, pair, "greeting_read", at=at + timedelta(seconds=2), number=n
            )
            pair = transition(
                pipeline, pair, "initial_contact", at=at + timedelta(seconds=3), number=n
            )
    metrics = service(pipeline.database)
    first = metrics.compute(
        compute_input(pair, start=NOW + timedelta(days=1), end=NOW + timedelta(days=2)),
        now=NOW + timedelta(days=3),
    )
    second = metrics.compute(
        compute_input(pair, start=NOW + timedelta(days=2), end=NOW + timedelta(days=3)),
        now=NOW + timedelta(days=3),
    )
    report = metrics.diagnose(
        dict(
            candidate_id="CAND_DEMO",
            current_metric_ids=[m["metric_id"] for m in second["metrics"]],
            previous_metric_ids=[m["metric_id"] for m in first["metrics"]],
        ),
        now=NOW + timedelta(days=3),
    )
    assert [d["diagnosis_code"] for d in report["diagnoses"]] == ["funnel_blocked_at_read"]
    item = report["diagnoses"][0]
    stored = metrics.get_diagnosis(item["diagnosis_id"], "CAND_DEMO")
    assert stored.diagnosis_code == "funnel_blocked_at_read"
    replay = metrics.diagnose(
        dict(
            candidate_id="CAND_DEMO",
            current_metric_ids=[m["metric_id"] for m in reversed(second["metrics"])],
            previous_metric_ids=[m["metric_id"] for m in reversed(first["metrics"])],
        ),
        now=NOW + timedelta(days=3),
    )
    assert replay == report
    with pipeline.database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM pipeline_stage_metrics").fetchone()[0] == 19
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM pipeline_stage_metrics WHERE diagnosis_id IS NOT NULL"
            ).fetchone()[0]
            == 1
        )
    with pytest.raises(ContractValidationError):
        metrics.get_diagnosis(item["diagnosis_id"], "CAND_OTHER")


def test_content_hash_version_is_not_a_comparable_generation_harness_version(tmp_path):
    pipeline, pair = prepared(tmp_path)
    assert pair[0].draft_version.startswith("CONTENT_")
    assert service(pipeline.database).facts("CAND_DEMO")[0].dimension_greeting_version is None
