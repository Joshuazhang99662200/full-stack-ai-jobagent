import json
from datetime import datetime
from pathlib import Path

from typer.testing import CliRunner

from jobagent.cli.app import app
from tests.connectors.test_mcp_stdio import configuration
from tests.storage.test_mcp_repository import NOW, call, setup_round

RUNNER = CliRunner()


def private_files(tmp_path, monkeypatch):
    import jobagent.cli.mcp_calls as adapter

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz is None else NOW.astimezone(tz)

    monkeypatch.setattr(adapter, "datetime", Clock)
    db, rules, _, run = setup_round(tmp_path, monkeypatch)
    private = tmp_path / ".jobagent"
    private.mkdir()
    # The test database must use the same private path as the public CLI.
    destination = private / "mcp.sqlite3"
    destination.write_bytes(db.path.read_bytes())
    snapshot = private / "rules.json"
    snapshot.write_text(rules.model_dump_json(), encoding="utf-8")
    transport = private / "transport.json"
    transport.write_text(configuration(tmp_path).model_dump_json(), encoding="utf-8")
    batch = private / "batch.json"
    batch.write_text(
        json.dumps([call("synthetic", operation="search").model_dump(mode="json")]),
        encoding="utf-8",
    )
    return destination, rules, run, snapshot, transport, batch


def test_mcp_group_has_guarded_execution_and_explicit_fact_commands():
    result = RUNNER.invoke(app, ["mcp", "--help"])
    assert result.exit_code == 0, result.output
    for name in (
        "round-start",
        "status",
        "round-close",
        "batch",
        "reconcile",
        "delivery-prepare",
        "delivery-record",
        "delivery-reconcile",
    ):
        assert name in result.output


def test_cli_executes_fake_stdio_once_then_replays_receipt(tmp_path, monkeypatch):
    database, rules, _, snapshot, transport, batch = private_files(tmp_path, monkeypatch)
    argv = [
        "mcp",
        "batch",
        str(batch),
        "--transport",
        str(transport),
        "--candidate",
        rules.candidate_id,
        "--rules-file",
        str(snapshot),
        "--database",
        str(database),
    ]
    first = RUNNER.invoke(app, argv)
    assert first.exit_code == 0, first.output
    body = json.loads(first.output)
    assert body[0]["status"] == "success"
    assert body[0]["selection"]["requested"] == 3
    assert body[0]["selection"]["taken_count"] == 1
    assert body[0]["selection"]["shortfall"] == 2
    log = tmp_path / "requests.jsonl"
    old = log.read_bytes()
    replay = RUNNER.invoke(app, argv)
    assert replay.exit_code == 0, replay.output
    assert json.loads(replay.output) == body and log.read_bytes() == old


def test_cli_status_requires_exact_candidate_without_sending(tmp_path, monkeypatch):
    database, rules, _, _, _, _ = private_files(tmp_path, monkeypatch)
    result = RUNNER.invoke(
        app,
        [
            "mcp",
            "status",
            "MCP_ONE",
            "--candidate",
            rules.candidate_id,
            "--database",
            str(database),
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["actual_calls"] == 0
    foreign = RUNNER.invoke(
        app, ["mcp", "status", "MCP_ONE", "--candidate", "CAND_OTHER", "--database", str(database)]
    )
    assert foreign.exit_code != 0 and "error" in json.loads(foreign.output)
    assert not (tmp_path / "requests.jsonl").exists()


def test_cli_private_input_guard_rejects_public_transport_without_dispatch(tmp_path, monkeypatch):
    database, rules, _, snapshot, _transport, batch = private_files(tmp_path, monkeypatch)
    public = Path("C:/SYNTHETIC_PUBLIC/mcp-transport.json")
    result = RUNNER.invoke(
        app,
        [
            "mcp",
            "batch",
            str(batch),
            "--transport",
            str(public),
            "--candidate",
            rules.candidate_id,
            "--rules-file",
            str(snapshot),
            "--database",
            str(database),
        ],
    )
    assert result.exit_code != 0 and "error" in json.loads(result.output)
    assert "private" in json.loads(result.output)["error"]["message"].lower()
    assert not (tmp_path / "requests.jsonl").exists()


def test_cli_round_start_replay_and_close_do_not_bill_any_calls(tmp_path, monkeypatch):
    from jobagent.schemas.mcp_calls import McpRoundRequest

    database, rules, run, snapshot, _, _ = private_files(tmp_path, monkeypatch)
    request_path = snapshot.parent / "round.json"
    request_path.write_text(
        json.dumps(
            run.model_dump(
                mode="json",
                include=set(McpRoundRequest.model_fields),
                exclude={"code_revision"},
            )
        ),
        encoding="utf-8",
    )
    start = RUNNER.invoke(
        app,
        [
            "mcp",
            "round-start",
            str(request_path),
            "--rules-file",
            str(snapshot),
            "--database",
            str(database),
        ],
    )
    assert start.exit_code == 0, start.output
    close = RUNNER.invoke(
        app,
        [
            "mcp",
            "round-close",
            run.run_id,
            "--candidate",
            rules.candidate_id,
            "--database",
            str(database),
        ],
    )
    assert close.exit_code == 0, close.output
    body = json.loads(close.output)
    assert body["closed"] and not body["activated"] and body["actual_calls"] == 0
    assert not (tmp_path / "requests.jsonl").exists()


def test_cli_gate_is_nonzero_and_blocks_further_transport(tmp_path, monkeypatch):
    database, rules, _, snapshot, transport, batch = private_files(tmp_path, monkeypatch)
    transport.write_text(configuration(tmp_path, "gate").model_dump_json(), encoding="utf-8")
    argv = [
        "mcp",
        "batch",
        str(batch),
        "--transport",
        str(transport),
        "--candidate",
        rules.candidate_id,
        "--rules-file",
        str(snapshot),
        "--database",
        str(database),
    ]
    first = RUNNER.invoke(app, argv)
    assert first.exit_code == 1, first.output
    assert json.loads(first.output)[0]["status"] == "gate"
    log = tmp_path / "requests.jsonl"
    previous = log.read_bytes()
    batch.write_text(
        json.dumps(
            [call("another", operation="search", batch="BATCH_TWO").model_dump(mode="json")]
        ),
        encoding="utf-8",
    )
    second = RUNNER.invoke(app, argv)
    assert second.exit_code == 1 and "halt" in second.output.lower()
    assert log.read_bytes() == previous


def test_cli_unknown_reconcile_preserves_usage_and_stop(tmp_path, monkeypatch):
    from jobagent.schemas.mcp_calls import McpCallReconciliation, McpProviderResult

    database, rules, _, snapshot, transport, batch = private_files(tmp_path, monkeypatch)
    transport.write_text(configuration(tmp_path, "unknown").model_dump_json(), encoding="utf-8")
    first = RUNNER.invoke(
        app,
        [
            "mcp",
            "batch",
            str(batch),
            "--transport",
            str(transport),
            "--candidate",
            rules.candidate_id,
            "--rules-file",
            str(snapshot),
            "--database",
            str(database),
        ],
    )
    assert first.exit_code == 1 and json.loads(first.output)[0]["status"] == "unknown"
    reference = snapshot.parent / "reconciliation.json"
    reference.write_text(
        McpCallReconciliation(
            call_id="synthetic",
            result=McpProviderResult(status="failed"),
            observed_at=NOW,
            observed_by="synthetic owner",
            source_reference="synthetic actual readback",
            positive_readback=True,
        ).model_dump_json(),
        encoding="utf-8",
    )
    result = RUNNER.invoke(
        app,
        [
            "mcp",
            "reconcile",
            str(reference),
            "--candidate",
            rules.candidate_id,
            "--database",
            str(database),
        ],
    )
    assert result.exit_code == 0, result.output
    body = json.loads(result.output)
    assert body["status"] == "failed" and body["budget"]["actual_calls"] == 1
    assert body["budget"]["halted"]
