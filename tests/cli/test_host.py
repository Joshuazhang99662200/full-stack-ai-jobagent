import json
from datetime import UTC, datetime

from typer.testing import CliRunner

from jobagent.cli.app import app

runner = CliRunner()


def test_host_migration_cli_keeps_private_inputs_out_of_errors_and_verifies_rows(tmp_path):
    from tests.storage.test_host_migration import fixture

    source, _, config = fixture(tmp_path)
    config_path = tmp_path / "mapping.json"
    config_path.write_text(config.model_dump_json(), encoding="utf-8")
    db = ["--database", str(tmp_path / "private.sqlite3")]
    inspect = runner.invoke(app, ["host", "inspect-queue", str(source)])
    assert inspect.exit_code == 0, inspect.output
    assert json.loads(inspect.stdout)["rows"] == 40 and "合成公司1" not in inspect.stdout
    result = runner.invoke(app, ["host", "migrate-queue", str(source), str(config_path), *db])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["source_rows"] == 40
    checked = runner.invoke(app, ["host", "verify-migration", config.migration_id, *db])
    assert checked.exit_code == 0 and json.loads(checked.stdout)["valid"]
    projected = tmp_path / "projection.jsonl"
    result = runner.invoke(app, ["host", "project-queue", config.migration_id, str(projected), *db])
    assert result.exit_code == 0 and len(projected.read_text(encoding="utf-8").splitlines()) == 40
    source.write_text('{"PRIVATE_SENTINEL":', encoding="utf-8")
    bad = runner.invoke(app, ["host", "inspect-queue", str(source)])
    assert bad.exit_code == 1 and "PRIVATE_SENTINEL" not in bad.output


def test_page_observe_and_status_cli_are_resource_scoped(tmp_path):
    request = tmp_path / "page.json"
    request.write_text(
        json.dumps(
            dict(
                observation_id="CLI_PAGE",
                candidate_id="CAND_DEMO",
                source="boss",
                surface="messages",
                state="not_loaded",
                reload_count=1,
                observed_at=datetime.now(UTC).isoformat(),
                evidence_reference="SCREENSHOT",
            )
        ),
        encoding="utf-8",
    )
    db = ["--database", str(tmp_path / "private.sqlite3")]
    result = runner.invoke(app, ["host", "page-observe", str(request), *db])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["action"] == "unconfirmed"
    state = runner.invoke(app, ["host", "page-status", "CAND_DEMO", *db])
    assert (
        state.exit_code == 0 and json.loads(state.stdout)["boss/messages"]["state"] == "not_loaded"
    )


def test_migrate_cli_actually_passes_separate_sent_file(tmp_path):
    from tests.storage.test_host_migration import fixture

    source, _, config = fixture(tmp_path)
    config = config.model_copy(update={"expected_sent_count": 8, "sent_row_id_field": "row"})
    config_path = tmp_path / "mapping.json"
    config_path.write_text(config.model_dump_json(), encoding="utf-8")
    sent = tmp_path / "sent.jsonl"
    sent.write_text(
        "\n".join(json.dumps({"row": str(i), "sent_at": None}) for i in range(1, 9)),
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        [
            "host",
            "migrate-queue",
            str(source),
            str(config_path),
            "--sent-file",
            str(sent),
            "--database",
            str(tmp_path / "private.sqlite3"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["sent_source_backup_path"]


def test_backfill_plan_cli_uses_explicit_private_priority(tmp_path):
    from tests.storage.test_host_migration import NOW, adapter, fixture

    source, _, config = fixture(tmp_path)
    db = tmp_path / "private.sqlite3"
    adapter().migrate(source, db, config, now=NOW)
    result = runner.invoke(
        app,
        [
            "host",
            "backfill-plan",
            config.migration_id,
            "--candidate",
            config.candidate_id,
            "--priority",
            "12,13,14,18,10,34,36,37",
            "--database",
            str(db),
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["rows"][0]["row_id"] == "12"


def test_private_message_diff_cli_reports_without_auto_rules(tmp_path):
    from jobagent.schemas.message_diff import MessageDiffInput
    from tests.jobs.test_message_diff import sample
    from tests.storage.test_job_intake_service import setup

    service, _, _ = setup(tmp_path)
    path = tmp_path / "private-comparison.json"
    path.write_text(MessageDiffInput.model_validate(sample()).model_dump_json(), encoding="utf-8")
    db = ["--database", str(service.database.path)]
    result = runner.invoke(app, ["host", "message-diff", str(path), *db])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["categories"] == ["fact_correction"]
    report = runner.invoke(app, ["host", "diff-report", "CAND_DEMO", *db])
    assert report.exit_code == 0, report.output
    assert json.loads(report.stdout)["evaluation_candidates"] == []
    rules = runner.invoke(app, ["host", "confirmed-rules", "CAND_DEMO", *db])
    assert rules.exit_code == 0 and json.loads(rules.stdout) == []
    invalid = json.loads(path.read_text(encoding="utf-8"))
    invalid["initial_hash"] = "PRIVATE_SENTINEL"
    path.write_text(json.dumps(invalid), encoding="utf-8")
    failure = runner.invoke(app, ["host", "message-diff", str(path), *db])
    assert failure.exit_code == 1 and "PRIVATE_SENTINEL" not in failure.output
