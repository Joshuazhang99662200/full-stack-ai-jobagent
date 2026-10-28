# ruff: noqa: RUF001 -- Preserve Chinese source punctuation.
import json

from typer.testing import CliRunner

from jobagent.cli.app import app

runner = CliRunner()


def test_browser_import_captures_raw_jd_and_query_in_private_ledger(tmp_path):
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
        }
    ]
    path = tmp_path / "observations.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    database = tmp_path / "private.sqlite3"
    result = runner.invoke(
        app, ["jobs", "import-observations", str(path), "--database", str(database)]
    )
    assert result.exit_code == 0, result.output
    item = json.loads(result.stdout)["stored"][0]
    assert item["snapshot_id"]
    from jobagent.storage.database import Database
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
