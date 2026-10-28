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
