import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from jobagent.cli.app import app
from tests.bridge.test_worker import MANIFEST, gateway, prepare, request

runner = CliRunner()


def invoke(*args: str) -> tuple[int, dict[str, object] | list[object]]:
    result = runner.invoke(app, ["worker", *args])
    try:
        return result.exit_code, json.loads(result.stdout)
    except ValueError:
        return result.exit_code, {"unparsed": result.output}


def test_cli_fetch_returns_record_ids_and_a_durable_completion(tmp_path: Path) -> None:
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "local.yaml").write_text(yaml.safe_dump(MANIFEST.model_dump(mode="json")))
    handoff = tmp_path / "fetch.json"
    handoff.write_text(request().model_dump_json(), encoding="utf-8")
    db = ("--database", str(tmp_path / "worker.sqlite3"))
    args = ("ingest", str(handoff), "--sources-dir", str(sources), *db)
    code, first = invoke(*args)
    assert code == 0 and isinstance(first, dict), first
    assert first["status"] == "stored"
    assert invoke(*args) == (0, first)
    code, events = invoke("events", *db)
    assert code == 0 and isinstance(events, list) and len(events) == 1
    assert "Synthetic job description" not in json.dumps(events)
    event_id = events[0]["event_id"]
    assert invoke("ack", event_id, *db)[0] == 0
    assert invoke("events", *db) == (0, [])
    assert invoke("show", "WFETCH_TEST", *db) == (0, first)


def test_worker_has_no_approval_or_unrestricted_sql_command(tmp_path: Path) -> None:
    assert runner.invoke(app, ["worker", "approve"]).exit_code == 2
    assert runner.invoke(app, ["worker", "sql"]).exit_code == 2
    gw = gateway(tmp_path)
    batch_id = prepare(gw, approve=False)
    code, refused = invoke(
        "claim-greeting",
        batch_id,
        "--platform",
        "local_test",
        "--session",
        "W1",
        "--database",
        str(gw.database.path),
    )
    assert code == 1 and isinstance(refused, dict), refused
    assert refused["error"]["code"] == "APPROVAL_REQUIRED"


def test_invalid_fetch_payload_never_creates_jobs(tmp_path: Path) -> None:
    handoff = tmp_path / "bad.json"
    handoff.write_text('{"task_id":"WFETCH_BAD","sql":"drop table jobs"}')
    code, refused = invoke("ingest", str(handoff), "--database", str(tmp_path / "db.sqlite3"))
    assert code == 1 and isinstance(refused, dict), refused
    assert refused["error"]["code"] == "CONTRACT_VALIDATION_ERROR"


def test_database_is_explicit_and_missing_task_is_an_error(tmp_path: Path) -> None:
    assert runner.invoke(app, ["worker", "events"]).exit_code == 2
    code, result = invoke("show", "WFETCH_MISSING", "--database", str(tmp_path / "db.sqlite3"))
    assert code == 1 and isinstance(result, dict)
    assert result["error"]["code"] == "CONTRACT_VALIDATION_ERROR"
