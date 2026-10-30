import json
from pathlib import Path

from typer.testing import CliRunner

from jobagent.cli.app import app

runner = CliRunner()


def call(tmp_path: Path, command: str, payload: dict):
    path = tmp_path / f"{command}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = runner.invoke(app, [
        "jobs", command, str(path), "--database", str(tmp_path / "budget.sqlite3"),
    ])
    return result, json.loads(result.stdout) if result.stdout.strip().startswith("{") else {}


def test_cli_reserves_before_detail_read_and_records_failure_without_refund(tmp_path):
    result, run = call(tmp_path, "sourcing-start", {
        "run_id": "RUN_1", "candidate_id": "CAND_DEMO", "source": "boss", "detail_limit": 1,
    })
    assert result.exit_code == 0, result.output
    assert run["daily_detail_limit"] <= 50
    payload = {
        "attempt_id": "ATT_1", "run_id": "RUN_1", "kind": "detail",
        "source_job_id": "synthetic",
        "url": "https://www.zhipin.com/job_detail/synthetic.html",
    }
    result, permit = call(tmp_path, "sourcing-reserve", payload)
    assert result.exit_code == 0 and permit["allowed"], result.output
    result, _ = call(tmp_path, "sourcing-result", {"attempt_id": "ATT_1", "outcome": "failed"})
    assert result.exit_code == 0, result.output
    result, denied = call(tmp_path, "sourcing-reserve", {**payload, "attempt_id": "ATT_2"})
    assert result.exit_code == 0 and denied["reason"] == "round_detail_limit", result.output
    budget = runner.invoke(app, [
        "jobs", "sourcing-budget", "--database", str(tmp_path / "budget.sqlite3"),
    ])
    assert budget.exit_code == 0, budget.output
    boss = json.loads(budget.stdout)["boss"]
    assert boss["read_today"] == 1 and boss["legacy_unmetered"] == 0


def test_cli_refuses_outside_board_detail_and_unconfigured_source(tmp_path):
    result, _ = call(tmp_path, "sourcing-start", {
        "run_id": "RUN_1", "candidate_id": "CAND_DEMO", "source": "boss",
    })
    assert result.exit_code == 0, result.output
    result, output = call(tmp_path, "sourcing-reserve", {
        "attempt_id": "ATT", "run_id": "RUN_1", "kind": "detail", "source_job_id": "synthetic",
        "url": "https://example.com/unrelated",
    })
    assert result.exit_code == 1
    assert output["error"]["code"] == "CONTRACT_VALIDATION_ERROR"
    result, _ = call(tmp_path, "sourcing-start", {
        "run_id": "RUN_2", "candidate_id": "CAND_DEMO", "source": "unknown",
    })
    assert result.exit_code == 1


def test_cli_does_not_accept_a_host_supplied_clock_or_daily_cap(tmp_path):
    result, output = call(tmp_path, "sourcing-start", {
        "run_id": "RUN_1", "candidate_id": "CAND_DEMO", "source": "boss",
        "opened_at": "PRIVATE_SENTINEL", "daily_detail_limit": 999,
    })
    assert result.exit_code == 1
    assert output["error"]["code"] == "CONTRACT_VALIDATION_ERROR"
    assert "PRIVATE_SENTINEL" not in result.stdout
