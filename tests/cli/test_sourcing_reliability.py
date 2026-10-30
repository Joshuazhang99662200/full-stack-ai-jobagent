import json

from typer.testing import CliRunner

from jobagent.cli.app import app


def test_read_reservation_records_failure_and_budget_remains_used(tmp_path):
    request = tmp_path / "request.json"
    request.write_text(json.dumps({
        "attempt_id": "SYN_READ", "source": "zhaopin",
        "target_url": "https://www.zhaopin.com/jobs/?kw=engineer", "profile": "standard",
        "expected_daily_cap": 50,
    }))
    db = str(tmp_path / "state.sqlite3")
    runner = CliRunner()
    reserved = runner.invoke(app, ["jobs", "reserve-read", str(request), "--database", db])
    assert reserved.exit_code == 0, reserved.stdout
    outcome = tmp_path / "outcome.json"
    outcome.write_text(json.dumps({"attempt_id": "SYN_READ", "status": "failed"}))
    recorded = runner.invoke(app, ["jobs", "record-read", str(outcome), "--database", db])
    assert recorded.exit_code == 0
    budget = runner.invoke(app, ["jobs", "sourcing-budget", "--database", db])
    assert json.loads(budget.stdout)["zhaopin"]["attempts_today"] == 1


def test_coverage_refuses_missing_disposition_and_accepts_partial_checkpoint(tmp_path):
    path = tmp_path / "coverage.json"
    data = {"input_ids": ["one", "two"], "dispositions": [
        {"item_id": "one", "status": "draft_ready", "reason": "Reviewed complete JD"},
    ], "stop_reason": "complete"}
    path.write_text(json.dumps(data))
    runner = CliRunner()
    assert runner.invoke(app, ["jobs", "check-coverage", str(path)]).exit_code != 0
    data["dispositions"].append(
        {"item_id": "two", "status": "deferred", "reason": "Budget exhausted"},
    )
    data.update(stop_reason="budget", last_cursor="page:2")
    path.write_text(json.dumps(data))
    result = runner.invoke(app, ["jobs", "check-coverage", str(path)])
    assert result.exit_code == 0 and json.loads(result.stdout)["stop_reason"] == "budget"


def test_empty_login_page_cannot_be_declared_complete(tmp_path):
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps({
        "input_ids": [], "dispositions": [], "stop_reason": "complete",
        "access_state": "login_required", "loaded": False,
    }))
    assert CliRunner().invoke(app, ["jobs", "check-coverage", str(path)]).exit_code != 0


def test_manual_job_identity_survives_jd_changes_at_same_source_url(tmp_path):
    path = tmp_path / "jd.txt"
    db = str(tmp_path / "manual.sqlite3")
    command = ["jobs", "add-jd", str(path), "--title", "Research Scientist", "--company",
               "Synthetic Labs", "--url", "https://example.test/job/one", "--database", db]
    runner = CliRunner()
    path.write_text("Design controlled research experiments and publish reproducible methods.")
    first = json.loads(runner.invoke(app, command).stdout)
    path.write_text("Design reliable experiments and lead a different research programme.")
    second = json.loads(runner.invoke(app, command).stdout)
    assert first["id"] == second["id"]
    history = runner.invoke(app, ["jobs", "observation-history", first["id"], "--database", db])
    assert len(json.loads(history.stdout)) == 2
    assert all(row["kind"] == "captured" for row in json.loads(history.stdout))


def test_invalid_read_receipt_cannot_leave_a_jd_snapshot(tmp_path):
    from jobagent.storage.database import Database
    from tests.storage.test_observation_history import record

    path = tmp_path / "observations.json"
    path.write_text(json.dumps([record(read_attempt_id="NOT_RESERVED").model_dump(mode="json")]))
    db = Database(tmp_path / "observations.sqlite3")
    result = CliRunner().invoke(app, [
        "jobs", "import-observations", str(path), "--database", str(db.path),
    ])
    assert result.exit_code != 0
    with db.connect() as connection:
        assert connection.execute("SELECT count(*) FROM jd_snapshots").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM job_observations").fetchone()[0] == 0
