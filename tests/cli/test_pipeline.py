import json
from datetime import UTC, datetime, timedelta

from typer.testing import CliRunner

from jobagent.cli.app import app

runner = CliRunner()


def request_file(tmp_path, name, value):
    path = tmp_path / name
    path.write_text(json.dumps(value, default=str), encoding="utf-8")
    return path


def created(tmp_path):
    from tests.storage.test_job_intake_service import setup

    core, intake, _ = setup(tmp_path)
    path = request_file(
        tmp_path,
        "private-create.json",
        dict(
            event_id="CLI_CREATE",
            candidate_id="CAND_DEMO",
            normalized_job_id=intake.job_id,
            intake_id=intake.intake_id,
            evidence_reference="PRIVATE_ENTRY",
            salary_minimum_k=18,
        ),
    )
    db = ["--database", str(core.database.path)]
    result = runner.invoke(app, ["pipeline", "create", str(path), *db])
    assert result.exit_code == 0, result.output
    return core.database, json.loads(result.stdout), db


def test_pipeline_create_form_list_history_and_candidate_scope(tmp_path):
    database, pair, db = created(tmp_path)
    assert pair["job"]["pipeline_state"] == "draft_pending" and pair["meta"]["version"] == 1
    listed = runner.invoke(app, ["pipeline", "list", "CAND_DEMO", *db])
    assert listed.exit_code == 0 and json.loads(listed.stdout) == [pair]
    form = runner.invoke(app, ["pipeline", "form", "CAND_DEMO", *db])
    assert form.exit_code == 0
    assert json.loads(form.stdout)[0]["pipeline_id"] == pair["job"]["pipeline_id"]
    with database.connect() as connection:
        source = dict(connection.execute("SELECT * FROM pipeline_job_form").fetchone())
    assert json.loads(form.stdout)[0]["title"] == source["title"]
    history = runner.invoke(
        app, ["pipeline", "history", pair["job"]["pipeline_id"], "--candidate", "CAND_DEMO", *db]
    )
    assert history.exit_code == 0 and json.loads(history.stdout)[0]["to_state"] == "draft_pending"
    wrong = runner.invoke(
        app, ["pipeline", "history", pair["job"]["pipeline_id"], "--candidate", "CAND_OTHER", *db]
    )
    assert wrong.exit_code == 1
    assert json.loads(runner.invoke(app, ["pipeline", "due", "CAND_DEMO", *db]).stdout) == []


def test_invalid_transition_is_logged_and_private_input_never_echoed(tmp_path):
    database, pair, db = created(tmp_path)
    payload = dict(
        event_id="BAD_JUMP",
        pipeline_id=pair["job"]["pipeline_id"],
        candidate_id="CAND_DEMO",
        expected_version=1,
        from_state="draft_pending",
        to_state="interviewed",
        changed_at=datetime.now(UTC),
        evidence_kind="owner_message",
        evidence_reference="PRIVATE_REPLY",
        reason_code="normal",
        owner_text="PRIVATE_SENTINEL",
    )
    path = request_file(tmp_path, "private-transition.json", payload)
    result = runner.invoke(app, ["pipeline", "transition", str(path), *db])
    assert result.exit_code == 1 and "PRIVATE_SENTINEL" not in result.output
    assert json.loads(result.stdout)["error"]["code"]
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM pipeline_rejections").fetchone()[0] == 1
    path.write_text('{"PRIVATE_SENTINEL":', encoding="utf-8")
    bad = runner.invoke(app, ["pipeline", "observe", str(path), *db])
    assert bad.exit_code == 1 and "PRIVATE_SENTINEL" not in bad.output


def test_pipeline_observe_and_sync_are_real_private_service_calls(tmp_path):
    _, pair, db = created(tmp_path)
    event = dict(
        event_id="CLI_PAUSE",
        pipeline_id=pair["job"]["pipeline_id"],
        candidate_id="CAND_DEMO",
        expected_version=pair["meta"]["version"],
        kind="pause",
        observed_at=datetime.now(UTC),
        evidence_kind="platform_state",
        evidence_reference="LOGIN_SCREEN",
    )
    path = request_file(tmp_path, "private-observe.json", event)
    result = runner.invoke(app, ["pipeline", "observe", str(path), *db])
    assert result.exit_code == 0 and json.loads(result.stdout)["meta"]["paused"]
    again = runner.invoke(app, ["pipeline", "observe", str(path), *db])
    assert again.exit_code == 0 and json.loads(again.stdout) == json.loads(result.stdout)
    sync = request_file(
        tmp_path,
        "private-sync.json",
        dict(
            event_id="CLI_SYNC",
            pipeline_id=pair["job"]["pipeline_id"],
            candidate_id="CAND_DEMO",
            expected_version=2,
        ),
    )
    refreshed = runner.invoke(app, ["pipeline", "sync", str(sync), *db])
    assert refreshed.exit_code == 0, refreshed.output
    assert json.loads(refreshed.stdout)["meta"]["paused"]  # Artifact reads never resume the host.


def test_pipeline_offline_migration_requires_candidate_for_reads_and_preserves_source(tmp_path):
    from tests.storage.test_pipeline_migration import fixture

    source, _, config = fixture(tmp_path)
    path = request_file(tmp_path, "private-mapping.json", config.model_dump(mode="json"))
    db = ["--database", str(tmp_path / "adopted.sqlite3")]
    before = source.read_bytes()
    inspected = runner.invoke(app, ["pipeline", "inspect", str(source)])
    assert inspected.exit_code == 0 and json.loads(inspected.stdout)["values_exposed"] is False
    assert "Synthetic Designer" not in inspected.stdout
    migrated = runner.invoke(app, ["pipeline", "migrate", str(source), str(path), *db])
    assert migrated.exit_code == 0, migrated.output
    assert (
        source.read_bytes() == before
        and json.loads(migrated.stdout)["source_rows"] == config.expected_count
    )
    checked = runner.invoke(
        app,
        [
            "pipeline",
            "verify-migration",
            config.migration_id,
            "--candidate",
            config.candidate_id,
            *db,
        ],
    )
    assert checked.exit_code == 0 and json.loads(checked.stdout)["valid"]
    missing_scope = runner.invoke(app, ["pipeline", "verify-migration", config.migration_id, *db])
    assert missing_scope.exit_code != 0
    wrong = runner.invoke(
        app, ["pipeline", "verify-migration", config.migration_id, "--candidate", "CAND_OTHER", *db]
    )
    assert wrong.exit_code == 1
    projection = tmp_path / "projection.jsonl"
    projected = runner.invoke(
        app,
        [
            "pipeline",
            "project",
            config.migration_id,
            str(projection),
            "--candidate",
            config.candidate_id,
            *db,
        ],
    )
    assert (
        projected.exit_code == 0
        and len(projection.read_text(encoding="utf-8").splitlines()) == config.expected_count
    )
    rolled = runner.invoke(
        app, ["pipeline", "rollback", config.migration_id, "--candidate", config.candidate_id, *db]
    )
    assert rolled.exit_code == 0 and json.loads(rolled.stdout)["restored"]
    assert source.read_bytes() == before


def test_pipeline_metrics_and_diagnoses_use_stored_facts_with_candidate_isolation(tmp_path):
    from tests.storage.test_pipeline_metrics import NOW, compute_input, prepared, transition

    pipeline, pair = prepared(tmp_path)
    pair = transition(pipeline, pair, "greeting_sent", at=NOW + timedelta(seconds=1))
    pair = transition(pipeline, pair, "greeting_read", at=NOW + timedelta(seconds=2))
    db = ["--database", str(pipeline.database.path)]
    path = request_file(tmp_path, "private-metric.json", compute_input(pair))
    result = runner.invoke(app, ["pipeline", "metrics", str(path), *db])
    assert result.exit_code == 0, result.output
    metrics = json.loads(result.stdout)["metrics"]
    item = next(
        m
        for m in metrics
        if m["stage_from"] == "greeting_sent" and m["stage_to"] == "greeting_read"
    )
    shown = runner.invoke(
        app, ["pipeline", "metric-show", item["metric_id"], "--candidate", "CAND_DEMO", *db]
    )
    assert shown.exit_code == 0 and json.loads(shown.stdout)["metric"]["numerator"] == 1
    wrong = runner.invoke(
        app, ["pipeline", "metric-show", item["metric_id"], "--candidate", "CAND_OTHER", *db]
    )
    assert wrong.exit_code == 1
    path = request_file(
        tmp_path,
        "private-diagnose.json",
        dict(candidate_id="CAND_DEMO", current_metric_ids=[m["metric_id"] for m in metrics]),
    )
    diagnosed = runner.invoke(app, ["pipeline", "diagnose", str(path), *db])
    assert diagnosed.exit_code == 0, diagnosed.output
    assert "diagnoses" in json.loads(diagnosed.stdout)
    missing = runner.invoke(
        app, ["pipeline", "diagnosis-show", "DIAG_MISSING", "--candidate", "CAND_DEMO", *db]
    )
    assert missing.exit_code == 1


def test_pipeline_cli_exposes_all_reviewable_operations():
    expected = {
        "create",
        "transition",
        "observe",
        "bind-send",
        "bind-reply",
        "sync",
        "list",
        "form",
        "history",
        "due",
        "inspect",
        "migrate",
        "verify-migration",
        "project",
        "rollback",
        "metrics",
        "diagnose",
        "metric-show",
        "diagnosis-show",
        "rule-propose",
        "rule-confirm",
        "confirmed-rules",
        "rule-review",
        "rule-show",
    }
    from typer.main import get_command

    commands = get_command(app).commands
    assert "pipeline" in commands
    assert set(commands["pipeline"].commands) == expected


def test_pipeline_rule_cli_proposal_confirmation_review_and_rollback(tmp_path, monkeypatch):
    from decimal import Decimal

    from jobagent.storage.pipeline_rules import PipelineRuleService
    from tests.storage.test_pipeline_rules import confirm, proposal, save_diag, seed

    service, diagnosis = seed(tmp_path, monkeypatch)
    # CLI wiring is tested here; stored-evidence freshness has separate integration tests.
    monkeypatch.setattr(
        PipelineRuleService, "require_current_evidence", lambda *_args, **_kwargs: None
    )
    db = ["--database", str(service.database.path)]
    path = request_file(tmp_path, "private-rule.json", proposal(diagnosis))
    result = runner.invoke(app, ["pipeline", "rule-propose", str(path), *db])
    assert result.exit_code == 0, result.output
    proposed = json.loads(result.stdout)
    assert (
        json.loads(runner.invoke(app, ["pipeline", "confirmed-rules", "CAND_DEMO", *db]).stdout)
        == []
    )
    shown = runner.invoke(
        app, ["pipeline", "rule-show", proposed["proposal_id"], "--candidate", "CAND_DEMO", *db]
    )
    assert shown.exit_code == 0 and json.loads(shown.stdout)["rule_hash"] == proposed["rule_hash"]
    wrong = runner.invoke(
        app, ["pipeline", "rule-show", proposed["proposal_id"], "--candidate", "CAND_OTHER", *db]
    )
    assert wrong.exit_code == 1
    path = request_file(tmp_path, "private-owner-rule.json", confirm(proposed))
    accepted = runner.invoke(app, ["pipeline", "rule-confirm", str(path), *db])
    assert accepted.exit_code == 0, accepted.output
    active = runner.invoke(app, ["pipeline", "confirmed-rules", "CAND_DEMO", *db])
    assert (
        active.exit_code == 0
        and json.loads(active.stdout)[0]["rule_text"] == "Use direct sentences."
    )
    rule = service.metric_rule(proposed["proposal_id"], "CAND_DEMO")
    bad = diagnosis.model_copy(
        update=dict(
            diagnosis_id="DIAG_CLI_REVIEW",
            rule_id=rule.rule_id,
            diagnosis_code="optimization_ineffective",
            optimized_rate=Decimal("0"),
            pre_rule_cumulative_rate=Decimal("0"),
            window_start=rule.effective_at,
            window_end=datetime.now(UTC),
        )
    )
    save_diag(service.database, bad)
    path = request_file(
        tmp_path,
        "private-review.json",
        dict(
            review_id="CLI_REVIEW",
            candidate_id="CAND_DEMO",
            rule_id=rule.rule_id,
            diagnosis_id=bad.diagnosis_id,
            diagnosis_digest=bad.source_digest,
        ),
    )
    reviewed = runner.invoke(app, ["pipeline", "rule-review", str(path), *db])
    assert reviewed.exit_code == 0, reviewed.output
    rollback = json.loads(reviewed.stdout)["rollback_proposal"]
    assert rollback["operation"] == "withdraw"
    assert (
        len(
            json.loads(runner.invoke(app, ["pipeline", "confirmed-rules", "CAND_DEMO", *db]).stdout)
        )
        == 1
    )
    path = request_file(
        tmp_path,
        "private-rollback-decision.json",
        confirm(rollback, confirmation_id="CLI_OWNER_ROLLBACK"),
    )
    withdrawn = runner.invoke(app, ["pipeline", "rule-confirm", str(path), *db])
    assert withdrawn.exit_code == 0, withdrawn.output
    assert (
        json.loads(runner.invoke(app, ["pipeline", "confirmed-rules", "CAND_DEMO", *db]).stdout)
        == []
    )


def test_pipeline_bind_reply_reuses_original_approval_without_sending(tmp_path):
    from tests.storage.test_pipeline_recontact import prepared

    intake, _, _, pipeline, job, _, store, conv, _, approval, payload = prepared(tmp_path)
    previous = store.list_events(conv.conversation_id)
    path = request_file(tmp_path, "private-bind-reply.json", payload)
    db = ["--database", str(intake.database.path)]
    result = runner.invoke(app, ["pipeline", "bind-reply", str(path), *db])
    assert result.exit_code == 0, result.output
    pair = json.loads(result.stdout)
    assert pair["job"]["draft_greeting"] == approval.reply.text
    assert pair["meta"]["recontact_approval_event_id"] == approval.event_id
    assert store.list_events(conv.conversation_id) == previous
    assert pipeline.repository.get(job.pipeline_id, job.candidate_id)[0].sent_at is None
    bad = request_file(
        tmp_path, "private-bind-reply-bad.json", {**payload, "text": "PRIVATE_SENTINEL"}
    )
    failed = runner.invoke(app, ["pipeline", "bind-reply", str(bad), *db])
    assert failed.exit_code == 1 and "PRIVATE_SENTINEL" not in failed.output
