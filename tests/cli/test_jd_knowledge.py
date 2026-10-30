# ruff: noqa: RUF001 -- Preserve Chinese source punctuation.
import json

from typer.testing import CliRunner

from jobagent.cli.app import app

runner = CliRunner()


def test_browser_import_captures_raw_jd_and_query_in_private_ledger(tmp_path):
    from datetime import datetime

    from jobagent.schemas.sourcing import (
        SourcingAttemptRequest,
        SourcingResultRequest,
        SourcingRunRequest,
    )
    from jobagent.storage.database import Database
    from jobagent.storage.sourcing_repository import SqliteSourcingRepository

    raw = "合成岗位职责：第一行保持原样。\n  第二行说明产品研究和项目交付，需要具备沟通能力。 "
    data = [
        {
            "source": "boss",
            "source_job_id": "synthetic",
            "url": "https://www.zhipin.com/job_detail/synthetic.html",
            "title": "合成产品岗位",
            "company": "合成公司",
            "location": "上海",
            "jd_raw": raw,
            "collected_at": "2026-10-28T10:00:00+08:00",
            "search_term": "合成 产品",
            "completeness": "full",
            "access_state": "authenticated",
            "read_attempt_id": "SYNTHETIC_BROWSER_READ",
        }
    ]
    path = tmp_path / "observations.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    database = tmp_path / "private.sqlite3"
    db = Database(database)
    db.migrate()
    ledger = SqliteSourcingRepository(db)
    now = datetime.fromisoformat(data[0]["collected_at"])
    ledger.start_run(SourcingRunRequest(
        run_id="SYNTHETIC_RUN", candidate_id="CAND_SYNTHETIC", source="boss",
    ), now=now, daily_cap=50)
    ledger.reserve(SourcingAttemptRequest(
        attempt_id="SYNTHETIC_BROWSER_READ", run_id="SYNTHETIC_RUN", kind="detail",
        source_job_id="synthetic", url=data[0]["url"],
    ), now=now)
    ledger.complete(SourcingResultRequest(
        attempt_id="SYNTHETIC_BROWSER_READ", outcome="complete",
    ), now=now)
    result = runner.invoke(
        app, ["jobs", "import-observations", str(path), "--database", str(database)]
    )
    assert result.exit_code == 0, result.output
    item = json.loads(result.stdout)["stored"][0]
    assert item["snapshot_id"]
    from jobagent.storage.jd_snapshot_repository import SqliteJDSnapshotRepository

    snap = SqliteJDSnapshotRepository(Database(database)).get(item["snapshot_id"])
    assert snap.jd_text == raw and snap.query_hit == "合成 产品"


def test_manual_jd_import_also_preserves_source_whitespace(tmp_path):
    raw = "\n合成岗位职责包括产品研究与项目交付。\n  负责需求评估和完整的验收与分析工作。\n"
    path = tmp_path / "jd.txt"
    path.write_text(raw, encoding="utf-8")
    database = tmp_path / "private.sqlite3"
    result = runner.invoke(
        app,
        [
            "jobs",
            "add-jd",
            str(path),
            "--title",
            "合成产品",
            "--company",
            "合成公司",
            "--url",
            "https://example.com/synthetic",
            "--database",
            str(database),
        ],
    )
    assert result.exit_code == 0, result.output
    from jobagent.storage.database import Database
    from jobagent.storage.jd_snapshot_repository import SqliteJDSnapshotRepository

    snapshots = SqliteJDSnapshotRepository(Database(database)).list_snapshots(
        json.loads(result.stdout)["id"],
    )
    assert snapshots and snapshots[0].jd_text == raw
    assert snapshots[0].query_hit is None


def test_snapshot_cli_keeps_listings_separate_and_does_not_echo_bad_input(tmp_path):
    path = tmp_path / "input.json"
    path.write_text(
        json.dumps(
            {
                "observation_id": "OBS_1",
                "job_id": "JOB_DEMO_1",
                "job_url": "https://example.com/synthetic",
                "platform": "manual",
                "fetched_at": "2026-10-28T10:00:00+08:00",
                "title": "合成岗位",
                "company": "合成公司",
                "jd_text": "列表摘要",
                "completeness": "listing",
            }
        ),
        encoding="utf-8",
    )
    result = runner.invoke(
        app, ["jobs", "snapshot", str(path), "--database", str(tmp_path / "private.sqlite3")]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["snapshot"]["completeness"] == "listing"
    path.write_text('{"bad":"PRIVATE_SENTINEL"}', encoding="utf-8")
    result = runner.invoke(
        app, ["jobs", "snapshot", str(path), "--database", str(tmp_path / "private.sqlite3")]
    )
    assert result.exit_code == 1 and "PRIVATE_SENTINEL" not in result.stdout


def test_factorize_update_plan_and_rollback_use_private_persisted_sources(tmp_path):
    from jobagent.jobs.lexicon import serialize_lexicon
    from tests.jobs.test_jd_knowledge import capture, lexicon

    database = tmp_path / "private.sqlite3"
    db = ["--database", str(database)]
    input_path = tmp_path / "capture.json"
    input_path.write_text(capture().model_dump_json(), encoding="utf-8")
    result = runner.invoke(app, ["jobs", "snapshot", str(input_path), *db])
    assert result.exit_code == 0, result.output
    snap_id = json.loads(result.stdout)["snapshot"]["snapshot_id"]
    lex_path = tmp_path / "lexicon.md"
    lex_path.write_text(serialize_lexicon(lexicon()), encoding="utf-8")
    result = runner.invoke(app, ["jobs", "factorize", snap_id, str(lex_path), *db])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["feature_set"]["features"]
    signals = tmp_path / "signals.json"
    signals.write_text(
        json.dumps(
            {
                "candidate_id": "CAND_DEMO",
                "baseline_queries": ["产品经理"],
                "signals": [],
            }
        ),
        encoding="utf-8",
    )
    result = runner.invoke(
        app, ["jobs", "lexicon-update", str(lex_path), str(signals), "--snapshot-id", snap_id, *db]
    )
    assert result.exit_code == 0, result.output
    update = json.loads(result.stdout)
    assert update["lexicon"]["lexicon_version"] == "v2"
    assert lex_path.read_text(encoding="utf-8") == serialize_lexicon(lexicon())
    result = runner.invoke(
        app, ["jobs", "lexicon-show", "CAND_DEMO", update["version_digest"], *db]
    )
    assert result.exit_code == 0, result.output
    restored = json.loads(result.stdout)
    assert restored["lexicon"] == update["lexicon"] and restored["markdown"]
    result = runner.invoke(
        app, ["jobs", "lexicon-show", "CAND_OTHER", update["version_digest"], *db]
    )
    assert result.exit_code == 1
    config = tmp_path / "plan.json"
    config.write_text(
        json.dumps(
            {
                "candidate_id": "CAND_DEMO",
                "source": "boss",
                "baseline_queries": ["产品经理"],
            }
        ),
        encoding="utf-8",
    )
    result = runner.invoke(
        app, ["jobs", "combinations", str(lex_path), str(config), "--snapshot-id", snap_id, *db]
    )
    assert result.exit_code == 0, result.output
    plan = json.loads(result.stdout)
    assert len(plan["ordered_queries"]) <= 3
    report = runner.invoke(app, ["jobs", "combinations-report", plan["version"], *db])
    assert report.exit_code == 0 and json.loads(report.stdout)["input"]["lexicon"]


def test_model_failures_fall_back_and_new_cli_errors_never_echo_input(tmp_path):
    from jobagent.jobs.lexicon import serialize_lexicon
    from tests.jobs.test_jd_knowledge import capture, lexicon

    db = ["--database", str(tmp_path / "private.sqlite3")]
    input_path = tmp_path / "capture.json"
    input_path.write_text(capture().model_dump_json(), encoding="utf-8")
    result = runner.invoke(app, ["jobs", "snapshot", str(input_path), *db])
    snap_id = json.loads(result.stdout)["snapshot"]["snapshot_id"]
    lex_path = tmp_path / "lexicon.md"
    lex_path.write_text(serialize_lexicon(lexicon()), encoding="utf-8")
    model = tmp_path / "model.json"
    model.write_text('{"invalid":"PRIVATE_SENTINEL"}', encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "jobs",
            "factorize",
            snap_id,
            str(lex_path),
            "--model-output",
            str(model),
            *db,
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["feature_set"]["factorization"] == "fallback"
    assert "PRIVATE_SENTINEL" not in result.stdout
