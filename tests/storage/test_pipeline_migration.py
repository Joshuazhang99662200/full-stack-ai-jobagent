import json
from datetime import UTC, datetime, timedelta

import pytest

from jobagent.errors import ContractValidationError
from jobagent.storage.database import Database
from jobagent.storage.host_migration import file_digest

NOW = datetime(2026, 10, 28, 10, tzinfo=UTC)


def fixture(tmp_path):
    from jobagent.schemas.pipeline_migration import PipelineMigrationConfig

    rows = [
        dict(
            id="7",
            platform="boss",
            source_job_id="synthetic-a",
            job_url="https://www.zhipin.com/job_detail/synthetic-a.html",
            title="Synthetic Designer",
            company="Synthetic Studio",
            salary_raw="18-25K",
            jd_points=["Design", "Figma"],
            draft_greeting="Synthetic draft",
            card_decision="rejected",
        ),
        dict(
            id="11",
            platform="zhaopin",
            source_job_id="synthetic-b",
            job_url="https://jobs.zhaopin.com/synthetic-b",
            title="Synthetic Researcher",
            company="Synthetic Research",
            salary_raw="unknown",
            jd_summary="Summary only",
            approved_greeting="Unverified historical approved text",
        ),
        dict(id="29", platform="boss", title="Unresolved source item", company="Unknown"),
    ]
    source = tmp_path / "private-queue.jsonl"
    source.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    config = PipelineMigrationConfig(
        migration_id="MIG_SYNTHETIC",
        candidate_id="CAND_DEMO",
        domain="design",
        expected_count=3,
        expected_row_ids=["7", "11", "29"],
        sent_row_ids=["11"],
        job_id_mode="platform_source_id",
        derived_entered_at=NOW - timedelta(days=1),
        derived_evidence_reference="PRIVATE_ROUND_LOG",
        salary_minimum_k=18,
    )
    return source, rows, config


def adapter():
    from jobagent.storage.pipeline_migration import PipelineMigrator

    return PipelineMigrator()


def test_migration_preserves_original_ids_partial_text_and_unproven_send_claims(tmp_path):
    source, rows, config = fixture(tmp_path)
    before = source.read_bytes()
    database = tmp_path / "private.sqlite3"
    result = adapter().migrate(source, database, config, now=NOW)
    assert result["source_rows"] == 3 and result["pipeline_rows"] == 2
    assert result["deferred_row_ids"] == ["29"] and result["proof_pending"] == 1
    assert source.read_bytes() == before
    assert adapter().migrate(source, database, config, now=NOW + timedelta(hours=1))["replayed"]
    verified = adapter().verify(database, config.migration_id, candidate_id=config.candidate_id)
    assert verified["valid"] and verified["row_ids"] == ["7", "11", "29"]
    with Database(database).connect() as connection:
        jobs = connection.execute("SELECT * FROM pipeline_jobs ORDER BY job_id").fetchall()
        assert jobs[0]["pipeline_state"] == "draft_pending"  # A card rejection is not abandonment.
        assert jobs[1]["pipeline_state"] == "greeting_sent"
        assert all(row["jd_text"] is None and row["jd_text_hash"] is None for row in jobs)
        assert all(
            row["sent_greeting"] is None
            and row["sent_text_hash"] is None
            and row["sent_at"] is None
            for row in jobs
        )
        assert all(not row["resume_requested"] and row["resume_file_id"] is None for row in jobs)
        assert json.loads(jobs[0]["jd_points"]) == rows[0]["jd_points"]
        meta = [
            json.loads(row[0]) for row in connection.execute("SELECT meta_json FROM pipeline_meta")
        ]
        assert all(m["entered_time_basis"] == "derived" for m in meta)
        assert sorted(m["proof_status"] for m in meta) == ["not_sent", "proof_pending"]
    projection = tmp_path / "projection.jsonl"
    adapter().project(database, config.migration_id, projection, candidate_id=config.candidate_id)
    projected = [json.loads(line) for line in projection.read_text(encoding="utf-8").splitlines()]
    assert [row["id"] for row in projected] == ["7", "11", "29"]
    assert all(row["runtime"]["completeness"] == "partial" for row in projected)
    assert all(row["runtime"]["snapshot_state"] == "snapshot_pending" for row in projected)
    assert projected[2]["runtime"]["identity_unverified"]


def test_wrong_count_identity_or_replayed_input_never_changes_database(tmp_path):
    from jobagent.storage.pipeline_migration import migration_database_digest

    source, rows, config = fixture(tmp_path)
    database = tmp_path / "private.sqlite3"
    Database(database).migrate()
    before = migration_database_digest(database)
    with pytest.raises(ContractValidationError):
        adapter().migrate(
            source, database, config.model_copy(update={"expected_count": 4}), now=NOW
        )
    assert migration_database_digest(database) == before
    result = adapter().migrate(source, database, config, now=NOW)
    rows[0]["source_job_id"] = "changed-target"
    source.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    with pytest.raises(ContractValidationError):
        adapter().migrate(source, database, config, now=NOW)
    assert (
        adapter().verify(database, config.migration_id)["source_digest"] == result["source_digest"]
    )


def test_missing_entry_time_is_not_filled_with_migration_time(tmp_path):
    source, _, config = fixture(tmp_path)
    database = tmp_path / "private.sqlite3"
    with pytest.raises(ContractValidationError):
        adapter().migrate(
            source,
            database,
            config.model_copy(
                update={"derived_entered_at": None, "derived_evidence_reference": None}
            ),
            now=NOW,
        )
    assert not database.exists()


def test_unknown_ids_candidate_mismatch_duplicate_jobs_and_extra_points_are_rejected(tmp_path):
    source, rows, config = fixture(tmp_path)
    variants = [
        config.model_copy(update={"expected_row_ids": ["7", "11", "missing"]}),
        config.model_copy(update={"sent_row_ids": ["missing"]}),
    ]
    for value in variants:
        with pytest.raises(ContractValidationError):
            adapter().migrate(source, tmp_path / "private.sqlite3", value, now=NOW)
    rows[1]["candidate_id"] = "CAND_OTHER"
    source.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    with pytest.raises(ContractValidationError):
        adapter().migrate(source, tmp_path / "private.sqlite3", config, now=NOW)
    source, rows, config = fixture(tmp_path)
    rows[0]["jd_points"] = ["one", "two", "three", "four"]
    source.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    with pytest.raises(ContractValidationError):
        adapter().migrate(source, tmp_path / "private.sqlite3", config, now=NOW)


def test_rollback_is_guarded_and_input_backup_cannot_be_projected_over(tmp_path):
    from pathlib import Path

    source, _, config = fixture(tmp_path)
    database = tmp_path / "private.sqlite3"
    Database(database).migrate()
    result = adapter().migrate(source, database, config, now=NOW)
    for target in (
        source,
        database,
        Path(result["source_backup_path"]),
        Path(result["backup_path"]),
    ):
        with pytest.raises(ContractValidationError):
            adapter().project(database, config.migration_id, target)
    with pytest.raises(ContractValidationError):
        adapter().verify(database, config.migration_id, candidate_id="CAND_OTHER")
    restored = adapter().rollback(database, config.migration_id, candidate_id="CAND_DEMO")
    assert restored["restored"] and file_digest(source) == result["source_digest"]
    with Database(database).connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM pipeline_jobs").fetchone()[0] == 0
    result = adapter().migrate(source, database, config, now=NOW)
    with Database(database).connect() as connection, connection:
        connection.execute(
            "UPDATE pipeline_meta SET meta_json = json_set(meta_json, '$.paused', json('true'))"
        )
    with pytest.raises(ContractValidationError):
        adapter().rollback(database, config.migration_id)


def test_explicit_platform_prefix_mapping_preserves_original_full_job_ids(tmp_path):
    source, rows, config = fixture(tmp_path)
    rows[0]["job_id"] = "BOSS-synthetic-a"
    rows[1]["job_id"] = "ZL-synthetic-b"
    source.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    config = config.model_copy(
        update={"job_id_mode": "preserve", "job_id_prefixes": {"boss": "BOSS-", "zhaopin": "ZL-"}}
    )
    database = tmp_path / "private.sqlite3"
    adapter().migrate(source, database, config, now=NOW)
    with Database(database).connect() as connection:
        actual = [
            row[0] for row in connection.execute("SELECT job_id FROM pipeline_jobs ORDER BY job_id")
        ]
    assert actual == ["BOSS-synthetic-a", "ZL-synthetic-b"]


def test_duplicate_source_targets_are_rejected_before_activation(tmp_path):
    source, rows, config = fixture(tmp_path)
    rows[1].update(platform="boss", source_job_id="synthetic-a", job_url=rows[0]["job_url"])
    source.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    database = tmp_path / "private.sqlite3"
    with pytest.raises(ContractValidationError):
        adapter().migrate(source, database, config, now=NOW)
    assert not database.exists()


def test_existing_active_target_failure_never_changes_original_database(tmp_path):
    from jobagent.schemas.pipeline import PipelineMeta
    from jobagent.storage.pipeline_migration import migration_database_digest
    from jobagent.storage.pipeline_repository import PipelineRepository
    from tests.jobs.test_pipeline_contracts import row

    source, _, config = fixture(tmp_path)
    database = tmp_path / "private.sqlite3"
    db = Database(database)
    db.migrate()
    job = row(
        job_id="boss-synthetic-a", job_url="https://www.zhipin.com/job_detail/synthetic-a.html"
    )
    meta = PipelineMeta(pipeline_id=job.pipeline_id, entered_evidence_reference="EXISTING_ENTRY")
    PipelineRepository(db).create(
        job, meta, event_id="PREEXISTING", evidence_reference="EXISTING_ENTRY"
    )
    before = migration_database_digest(database)
    with pytest.raises(ContractValidationError):
        adapter().migrate(source, database, config, now=NOW)
    assert migration_database_digest(database) == before


def test_unverified_legacy_sends_never_acquire_clock_or_formal_approval(tmp_path):
    from jobagent.storage.pipeline_repository import PipelineRepository

    source, _, config = fixture(tmp_path)
    database = tmp_path / "private.sqlite3"
    adapter().migrate(source, database, config, now=NOW)
    repository = PipelineRepository(Database(database))
    assert repository.due(config.candidate_id, now=NOW + timedelta(days=365)) == []
    with repository.database.connect() as connection:
        for table in (
            "outreach_approvals",
            "outreach_audits",
            "normalized_jobs",
            "jd_snapshots",
            "jd_feature_sets",
        ):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_verification_detects_later_identity_tampering_and_deferred_claims_are_explicit(tmp_path):
    source, _, config = fixture(tmp_path)
    config = config.model_copy(update={"sent_row_ids": ["11", "29"]})
    database = tmp_path / "private.sqlite3"
    result = adapter().migrate(source, database, config, now=NOW)
    assert result["deferred_send_claim_row_ids"] == ["29"]
    with Database(database).connect() as connection, connection:
        connection.execute(
            "UPDATE pipeline_jobs SET company = ? WHERE job_id = ?",
            ("Different target", "boss-synthetic-a"),
        )
    with pytest.raises(ContractValidationError):
        adapter().verify(database, config.migration_id)


def test_activation_time_is_import_time_and_declared_state_has_a_replay_snapshot(tmp_path):
    source, _, config = fixture(tmp_path)
    database = tmp_path / "private.sqlite3"
    adapter().migrate(source, database, config, now=NOW)
    with Database(database).connect() as connection:
        activated = connection.execute(
            "SELECT activated_at FROM pipeline_authorities WHERE candidate_id = ?",
            (config.candidate_id,),
        ).fetchone()[0]
        assert datetime.fromisoformat(activated) == NOW
        declared = connection.execute(
            "SELECT response_json FROM pipeline_requests WHERE event_id LIKE 'DECLARE_%'"
        ).fetchall()
        assert len(declared) == 1
        snapshot = json.loads(declared[0][0])
        assert snapshot["job"]["pipeline_state"] == "greeting_sent"
        assert snapshot["meta"]["proof_status"] == "proof_pending"
