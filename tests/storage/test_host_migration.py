# ruff: noqa: RUF001 -- Synthetic Chinese evidence punctuation.
import json
from datetime import UTC, datetime

import pytest

from jobagent.errors import ContractValidationError

NOW = datetime(2026, 10, 28, 9, tzinfo=UTC)


def fixture(tmp_path, count=40):
    from jobagent.schemas.host_migration import QueueMigrationConfig

    rows = [
        dict(
            n=i,
            board="boss",
            platform_id=f"synthetic-{i}",
            link=f"https://www.zhipin.com/job_detail/synthetic-{i}.html",
            title="合成设计岗位",
            company=f"合成公司{i}",
            summary="只有历史要点，非完整JD",
            state="awaiting_reply" if i <= 8 else "pending",
            full_jd_text_stored=False,
        )
        for i in range(1, count + 1)
    ]
    source = tmp_path / "queue.jsonl"
    source.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8"
    )
    config = QueueMigrationConfig(
        migration_id="MIG_SYNTHETIC",
        candidate_id="CAND_DEMO",
        domain="design",
        expected_count=40,
        sent_row_ids=[str(i) for i in range(1, 9)],
        fields=dict(
            row_id="n",
            platform="board",
            source_job_id="platform_id",
            job_url="link",
            title="title",
            company="company",
            summary="summary",
            status="state",
        ),
    )
    return source, rows, config


def adapter():
    from jobagent.storage.host_migration import HostQueueMigrator

    return HostQueueMigrator()


def test_exact_forty_rows_are_backed_up_migrated_and_projected_without_fabrication(tmp_path):
    source, rows, config = fixture(tmp_path)
    database = tmp_path / "private.sqlite3"
    result = adapter().migrate(source, database, config, now=NOW)
    assert result["source_rows"] == 40 and result["canonical_intakes"] == 40
    assert result["proof_pending"] == 8
    assert result["identity_verified"] == 0  # No captured timestamps, no guessed read.
    assert result["backup_path"]
    verified = adapter().verify(database, config.migration_id)
    assert verified["valid"] and verified["row_ids"] == [str(i) for i in range(1, 41)]
    assert adapter().migrate(source, database, config, now=NOW)["replayed"]
    output = tmp_path / "queue-projection.jsonl"
    adapter().project(database, config.migration_id, output)
    projected = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert [r["n"] for r in projected] == [r["n"] for r in rows]
    assert all(r["runtime"]["snapshot_state"] == "snapshot_pending" for r in projected)
    assert all(r["runtime"]["completeness"] == "partial" for r in projected)
    from jobagent.storage.database import Database

    with Database(database).connect() as connection:
        for table in [
            "normalized_jobs",
            "jd_feature_sets",
            "intake_signals",
            "outreach_approvals",
            "sent_tracking_roots",
        ]:
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        saved = json.loads(
            connection.execute(
                "SELECT legacy_snapshot_json FROM host_legacy_rows LIMIT 1"
            ).fetchone()[0]
        )
    assert saved["observed_at"] is None and saved["full_jd_text_stored"] is False


@pytest.mark.parametrize("count", [39, 41])
def test_wrong_counts_do_not_replace_existing_database(tmp_path, count):
    from jobagent.storage.database import Database
    from jobagent.storage.host_migration import database_digest

    source, _, config = fixture(tmp_path, count=count)
    db_path = tmp_path / "private.sqlite3"
    Database(db_path).migrate()
    before = database_digest(db_path)
    with pytest.raises(ContractValidationError):
        adapter().migrate(source, db_path, config, now=NOW)
    assert database_digest(db_path) == before


def test_duplicate_row_ids_and_changed_replay_are_rejected(tmp_path):
    source, rows, config = fixture(tmp_path)
    rows[-1]["n"] = 1
    source.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    with pytest.raises(ContractValidationError):
        adapter().migrate(source, tmp_path / "private.sqlite3", config, now=NOW)
    source, rows, config = fixture(tmp_path)
    db = tmp_path / "private.sqlite3"
    adapter().migrate(source, db, config, now=NOW)
    rows[0]["platform_id"] = "wrong-target"
    source.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    with pytest.raises(ContractValidationError):
        adapter().migrate(source, db, config, now=NOW)


def test_same_job_sources_merge_only_when_explicit_and_keep_all_source_bindings(tmp_path):
    source, rows, config = fixture(tmp_path)
    rows[1].update(platform_id=rows[0]["platform_id"], link=rows[0]["link"])
    source.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    with pytest.raises(ContractValidationError):
        adapter().migrate(source, tmp_path / "private.sqlite3", config, now=NOW)
    config = config.model_copy(update={"require_distinct_jobs": False})
    report = adapter().migrate(source, tmp_path / "private.sqlite3", config, now=NOW)
    assert report["source_rows"] == 40 and report["canonical_intakes"] == 39
    assert adapter().verify(tmp_path / "private.sqlite3", config.migration_id)["valid"]


def test_verified_rollback_restores_baseline_and_refuses_post_migration_activity(tmp_path):
    from jobagent.storage.database import Database
    from jobagent.storage.host_migration import database_digest

    source, _, config = fixture(tmp_path)
    db = tmp_path / "private.sqlite3"
    Database(db).migrate()
    baseline = database_digest(db)
    report = adapter().migrate(source, db, config, now=NOW)
    adapter().rollback(db, config.migration_id)
    assert database_digest(db) == baseline
    adapter().migrate(source, db, config.model_copy(update={"migration_id": "MIG_TWO"}), now=NOW)
    with Database(db).connect() as connection, connection:
        connection.execute("CREATE TABLE new_user_activity (value TEXT)")
        connection.execute("INSERT INTO new_user_activity VALUES ('synthetic')")
    with pytest.raises(ContractValidationError):
        adapter().rollback(db, "MIG_TWO")
    assert report["source_rows"] == 40


def test_inspection_only_reports_shape_not_private_values(tmp_path):
    source, _, _ = fixture(tmp_path)
    shape = adapter().inspect(source)
    assert shape["rows"] == 40 and "n" in shape["fields"]
    assert "合成公司1" not in json.dumps(shape, ensure_ascii=False)


def test_legacy_sent_claim_only_becomes_formal_when_bound_to_existing_tracking(tmp_path):
    from pydantic import HttpUrl

    from jobagent.schemas.host_migration import LegacyTrackingBinding
    from jobagent.storage.database import Database
    from jobagent.storage.sent_tracking_repository import SqliteSentTrackingRepository
    from tests.jobs.test_sent_tracking import proof

    source, rows, config = fixture(tmp_path)
    rows[0]["send_reference"] = proof().send_reference
    source.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    db = tmp_path / "private.sqlite3"
    adapter().migrate(source, db, config, now=NOW)
    request = LegacyTrackingBinding(
        migration_id=config.migration_id,
        row_id="1",
        candidate_id="CAND_DEMO",
        tracking_id="TRACK_ONE",
    )
    with pytest.raises(ContractValidationError):
        adapter().bind_tracking(db, request)
    SqliteSentTrackingRepository(Database(db)).start(
        proof().model_copy(
            update={"job_url": HttpUrl("https://www.zhipin.com/job_detail/synthetic-1.html")}
        ),
        candidate_id="CAND_DEMO",
        tracking_id="TRACK_ONE",
        now=NOW,
        next_poll_at=NOW.replace(hour=13),
    )
    assert adapter().bind_tracking(db, request)["bound"]
    assert adapter().bind_tracking(db, request)["bound"]


def test_separate_legacy_sent_file_is_preserved_without_fabricating_exact_send_time(tmp_path):
    from jobagent.storage.database import Database

    source, _, config = fixture(tmp_path)
    sent = tmp_path / "sent-tracking.jsonl"
    claims = [
        dict(
            row=str(i),
            send_reference=f"AUDIT_SYNTHETIC_{i}",
            sent_window={"start": "2026-10-27T15:11:00+08:00", "end": "2026-10-27T15:25:00+08:00"},
            exact_sent_at=None,
            check_count=0,
        )
        for i in range(1, 9)
    ]
    sent.write_text("\n".join(json.dumps(row) for row in claims), encoding="utf-8")
    config = config.model_copy(
        update={"sent_row_ids": [], "sent_row_id_field": "row", "expected_sent_count": 8}
    )
    db = tmp_path / "private.sqlite3"
    report = adapter().migrate(source, db, config, now=NOW, sent_source=sent)
    assert report["proof_pending"] == 8 and report["sent_source_backup_path"]
    with Database(db).connect() as connection:
        row = connection.execute(
            "SELECT sent_claim_json FROM host_legacy_rows WHERE row_id = '1'"
        ).fetchone()
        assert json.loads(row[0])["exact_sent_at"] is None
        assert connection.execute("SELECT COUNT(*) FROM sent_tracking_roots").fetchone()[0] == 0
    claims[0]["send_reference"] = "CHANGED"
    sent.write_text("\n".join(json.dumps(row) for row in claims), encoding="utf-8")
    with pytest.raises(ContractValidationError):
        adapter().migrate(source, db, config, now=NOW, sent_source=sent)


def test_projection_cannot_replace_database_or_any_original_backup(tmp_path):
    source, _, config = fixture(tmp_path)
    db = tmp_path / "private.sqlite3"
    report = adapter().migrate(source, db, config, now=NOW)
    from pathlib import Path

    for target in (source, db, Path(report["backup_path"]), Path(report["source_backup_path"])):
        with pytest.raises(ContractValidationError):
            adapter().project(db, config.migration_id, target)


def test_expected_queue_size_is_an_explicit_private_parameter():
    from pydantic import ValidationError

    from jobagent.schemas.host_migration import QueueMigrationConfig

    with pytest.raises(ValidationError):
        QueueMigrationConfig(migration_id="MIG_GENERIC", candidate_id="CAND_DEMO", domain="design")
