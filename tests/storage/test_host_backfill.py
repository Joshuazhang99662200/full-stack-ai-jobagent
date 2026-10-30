from datetime import timedelta

import pytest

from jobagent.errors import ContractValidationError
from tests.storage.test_host_migration import NOW, adapter, fixture
from tests.storage.test_job_intake_service import command, setup


def test_backfill_plan_retains_all_rows_and_explicit_private_priority(tmp_path):
    from jobagent.storage.database import Database
    from jobagent.storage.host_backfill import HostBackfillService

    source, _, config = fixture(tmp_path)
    path = tmp_path / "private.sqlite3"
    adapter().migrate(source, path, config, now=NOW)
    service = HostBackfillService(Database(path))
    result = service.plan(
        config.migration_id,
        config.candidate_id,
        priority_ids=["12", "13", "14", "18", "10", "34", "36", "37", "404"],
    )
    assert len(result["rows"]) == 40
    assert [r["row_id"] for r in result["rows"]][:8] == [
        "12",
        "13",
        "14",
        "18",
        "10",
        "34",
        "36",
        "37",
    ]
    assert result["unknown_priority_ids"] == ["404"]
    assert all(r["status"] == "partial_not_in_strategy" for r in result["rows"])
    assert all(r["legacy_snapshot_version"] == 0 for r in result["rows"])
    with pytest.raises(ContractValidationError):
        service.plan(config.migration_id, "CAND_OTHER")


def real_attempt(service, row, snap):
    from jobagent.schemas.jd_snapshot import JDSnapshotInput
    from jobagent.schemas.sourcing import (
        SourcingAttemptRequest,
        SourcingResultRequest,
        SourcingRunRequest,
    )
    from jobagent.storage.sourcing_repository import SqliteSourcingRepository

    meter = SqliteSourcingRepository(service.database)
    meter.start_run(
        SourcingRunRequest(
            run_id="RUN_BACKFILL", candidate_id=row.candidate_id, source=row.platform
        ),
        now=NOW,
        daily_cap=50,
    )
    meter.reserve(
        SourcingAttemptRequest(
            attempt_id="READ_BACKFILL",
            run_id="RUN_BACKFILL",
            kind="detail",
            source_job_id=row.source_job_id,
            url=row.job_url,
        ),
        now=NOW,
    )
    data = snap.model_dump(
        exclude={"snapshot_id", "snapshot_version", "jd_text_hash", "content_digest"}
    )
    data.update(observation_id="REREAD", fetched_at=NOW + timedelta(seconds=1))
    capture = service.knowledge.capture(JDSnapshotInput.model_validate(data))
    meter.complete(
        SourcingResultRequest(attempt_id="READ_BACKFILL", outcome="complete"),
        now=NOW + timedelta(seconds=2),
    )
    return capture


def test_same_content_recapture_uses_actual_observation_time_and_budget(tmp_path):
    service, row, snap = setup(tmp_path)
    reread = real_attempt(service, row, snap)
    assert reread.snapshot.snapshot_id == snap.snapshot_id
    updated = service.attach_snapshot(
        command(
            row, snapshot_id=snap.snapshot_id, observation_id="REREAD", attempt_id="READ_BACKFILL"
        ),
        now=NOW + timedelta(seconds=3),
    )
    assert updated.snapshot_id == snap.snapshot_id
    assert service.knowledge.discoveries(snap.job_id)[-1].fetched_at == reread.discovery.fetched_at
    assert service.knowledge.discoveries(snap.job_id)[-1].query_hit is None


def test_wrong_or_missing_observation_cannot_reuse_completed_read(tmp_path):
    service, row, snap = setup(tmp_path)
    real_attempt(service, row, snap)
    for observation_id in ("MISSING", "OBS_1"):
        with pytest.raises(ContractValidationError):
            service.attach_snapshot(
                command(
                    row,
                    snapshot_id=snap.snapshot_id,
                    observation_id=observation_id,
                    attempt_id="READ_BACKFILL",
                ),
                now=NOW + timedelta(seconds=3),
            )


def test_backfill_records_legacy_to_full_lineage_after_core_validation(tmp_path):
    from jobagent.schemas.host_migration import QueueMigrationConfig
    from jobagent.storage.database import Database
    from jobagent.storage.host_backfill import HostBackfillService
    from jobagent.storage.job_intake_service import JobIntakeService
    from jobagent.storage.job_repository import SqliteJobRepository

    cached_service, _, snap = setup(tmp_path / "cached")
    cached_job = cached_service.jobs.get_job(snap.job_id)
    source, rows, config = fixture(tmp_path)
    rows = [
        dict(
            id="one",
            source="boss",
            url=str(cached_job.url),
            source_job_id="1",
            title=cached_job.title,
            company=cached_job.company,
            jd_summary="old summary",
        )
    ]
    import json

    source.write_text(json.dumps(rows[0]) + "\n", encoding="utf-8")
    config = QueueMigrationConfig(
        migration_id="ONE", candidate_id="CAND_DEMO", domain="design", expected_count=1
    )
    path = tmp_path / "private.sqlite3"
    adapter().migrate(source, path, config, now=NOW)
    database = Database(path)
    core = JobIntakeService(database)
    SqliteJobRepository(database).save_job(cached_job)
    row = core.repository.list_records("CAND_DEMO", "design")[0]
    row = core.resolve(command(row, job_id=cached_job.id), now=NOW)
    from jobagent.schemas.jd_snapshot import JDSnapshotInput

    data = snap.model_dump(
        exclude={"snapshot_id", "snapshot_version", "jd_text_hash", "content_digest"}
    )
    core.knowledge.capture(JDSnapshotInput.model_validate(data))
    reread = real_attempt(core, row, snap)
    payload = dict(
        migration_id="ONE",
        row_id="one",
        candidate_id="CAND_DEMO",
        snapshot=command(
            row,
            snapshot_id=reread.snapshot.snapshot_id,
            observation_id="REREAD",
            attempt_id="READ_BACKFILL",
        ),
    )
    service = HostBackfillService(database)
    result = service.attach(payload, now=NOW + timedelta(seconds=3))
    assert result["full_jd_text_stored"] and result["legacy_snapshot_version"] == 0
    assert result["snapshot_version"] == 1
    assert (
        result["query_hit"] is None
        and result["fetched_at"] == reread.discovery.fetched_at.isoformat()
    )
    assert service.attach(payload, now=NOW + timedelta(seconds=4)) == result
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM host_backfill_links").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM host_legacy_rows").fetchone()[0] == 1
    plan = service.plan("ONE", "CAND_DEMO")
    assert plan["rows"][0]["status"] == "snapshot_complete"


def test_changed_full_jd_preserves_versions_and_invalidates_old_derived_bindings(tmp_path):
    from jobagent.schemas.jd_snapshot import JDSnapshotInput
    from tests.storage.test_job_intake_service import draft_payload, full, policy

    service, row, old = full(tmp_path)
    row = service.factorize(command(row), policy(), proposal=None, now=NOW)
    row = service.submit_draft(draft_payload(row), now=NOW)
    assert row.feature_set_id and row.draft_digest
    job = service.jobs.get_job(row.job_id)
    changed_text = job.jd_raw + " New complete responsibility."
    service.jobs.save_job(job.model_copy(update={"jd_raw": changed_text}))
    data = old.model_dump(
        exclude={"snapshot_id", "snapshot_version", "jd_text_hash", "content_digest"}
    )
    data.update(observation_id="CHANGED_FULL", jd_text=changed_text, fetched_at=NOW)
    new = service.knowledge.capture(JDSnapshotInput.model_validate(data)).snapshot
    assert new.snapshot_version == old.snapshot_version + 1
    current = service.synchronize(row.intake_id, row.candidate_id, now=NOW)
    assert current.snapshot_id is None and current.feature_set_id is None
    assert current.draft_digest is None and current.plan_id is None
    assert service.knowledge.get(old.snapshot_id).jd_text == old.jd_text
    assert len(service.knowledge.list_snapshots(job.id)) == 2
    assert any(
        event.state.draft_digest == row.draft_digest
        for event in service.repository.history(row.intake_id, row.candidate_id)
    )


def test_reading_backfill_plan_never_advances_database_state(tmp_path):
    from jobagent.storage.database import Database
    from jobagent.storage.host_backfill import HostBackfillService
    from jobagent.storage.host_migration import database_digest

    source, _, config = fixture(tmp_path)
    path = tmp_path / "private.sqlite3"
    adapter().migrate(source, path, config, now=NOW)
    before = database_digest(path)
    HostBackfillService(Database(path)).plan(config.migration_id, config.candidate_id)
    assert database_digest(path) == before
