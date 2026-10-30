import json
from datetime import timedelta

import pytest

from jobagent.errors import ContractValidationError
from jobagent.storage.database import Database
from jobagent.storage.host_backfill import HostBackfillService
from jobagent.storage.pipeline_migration import PipelineMigrator, migration_database_digest
from jobagent.storage.pipeline_repository import PipelineRepository
from tests.storage.test_host_backfill import real_attempt
from tests.storage.test_job_intake_service import command, setup
from tests.storage.test_pipeline_migration import NOW, fixture


def migrated(tmp_path):
    core, intake, snapshot = setup(tmp_path)
    cached = core.jobs.get_job(intake.job_id)
    source, _, config = fixture(tmp_path)
    rows = [
        dict(
            id="alpha",
            platform="boss",
            source_job_id=cached.source_job_id,
            job_url=str(cached.url),
            title=cached.title,
            company=cached.company,
            jd_points=["Old source excerpt"],
        ),
        dict(id="unresolved", platform="boss", title="Unresolved", company="Synthetic"),
    ]
    source.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    config = config.model_copy(
        update={
            "expected_count": 2,
            "expected_row_ids": ["alpha", "unresolved"],
            "sent_row_ids": [],
        }
    )
    PipelineMigrator().migrate(source, core.database.path, config, now=NOW)
    core = type(core)(Database(core.database.path))
    pipeline, meta = PipelineRepository(core.database).list_records("CAND_DEMO")[0]
    intake = core.repository.get(intake.intake_id, intake.candidate_id)
    return core, intake, snapshot, pipeline, meta, config


def payload(config, intake, snapshot):
    return dict(
        migration_id=config.migration_id,
        row_id="alpha",
        candidate_id="CAND_DEMO",
        snapshot=command(
            intake,
            snapshot_id=snapshot.snapshot_id,
            observation_id="REREAD",
            attempt_id="READ_BACKFILL",
        ),
    )


def test_new_migration_dispatch_plan_is_complete_private_priority_and_read_only(tmp_path):
    core, _, _, pipeline, _, config = migrated(tmp_path)
    before = migration_database_digest(core.database.path)
    plan = HostBackfillService(core.database).plan(
        config.migration_id, "CAND_DEMO", ["unresolved", "alpha", "missing"]
    )
    assert [row["row_id"] for row in plan["rows"]] == ["unresolved", "alpha"]
    assert plan["unknown_priority_ids"] == ["missing"]
    pending, resolved = plan["rows"]
    assert pending["identity_unverified"] and pending["pipeline_id"] is None
    assert resolved["pipeline_id"] == pipeline.pipeline_id
    assert resolved["source_job_id"] == "1"
    assert resolved["legacy_snapshot_version"] == 0
    assert resolved["status"] == "partial_not_in_strategy"
    assert resolved["job_url"] == str(pipeline.job_url)
    assert migration_database_digest(core.database.path) == before
    with pytest.raises(ContractValidationError):
        HostBackfillService(core.database).plan(config.migration_id, "CAND_OTHER")


def test_attach_binds_exact_intake_and_true_lineage_and_replays_without_reread(
    tmp_path, monkeypatch
):
    core, intake, snapshot, pipeline, _, config = migrated(tmp_path)
    capture = real_attempt(core, intake, snapshot)
    request = payload(config, intake, capture.snapshot)
    service = HostBackfillService(core.database)
    link = service.attach(request, now=NOW + timedelta(seconds=3))
    actual, meta = PipelineRepository(core.database).get(pipeline.pipeline_id, "CAND_DEMO")
    assert actual.jd_text == snapshot.jd_text and meta.intake_id == intake.intake_id
    assert link["pipeline_id"] == actual.pipeline_id
    assert link["fetched_at"] == capture.discovery.fetched_at.isoformat()
    assert link["query_hit"] is None and link["discovery_kind"] == "manual"
    assert link["legacy_snapshot_version"] == 0 and link["snapshot_version"] == 1
    assert link["full_jd_text_stored"]
    monkeypatch.setattr(
        "jobagent.storage.job_intake_service.JobIntakeService.attach_snapshot",
        lambda *_a, **_kw: pytest.fail("Replay must not reread source artifacts"),
    )
    assert service.attach(request, now=NOW + timedelta(seconds=4)) == link
    with core.database.connect() as connection:
        assert connection.execute("SELECT count(*) FROM pipeline_backfill_links").fetchone()[0] == 1
        original = connection.execute(
            "SELECT source_line FROM pipeline_migration_rows WHERE row_id='alpha'"
        ).fetchone()[0]
        assert json.loads(original)["jd_points"] == ["Old source excerpt"]
    assert service.plan(config.migration_id, "CAND_DEMO")["rows"][0]["status"] == "full"
    changed = {**request, "row_id": "unresolved"}
    with pytest.raises(ContractValidationError):
        service.attach(changed, now=NOW + timedelta(seconds=4))


def test_wrong_identity_missing_budget_and_deferred_reject_before_attachment(tmp_path):
    core, intake, snapshot, _, _, config = migrated(tmp_path)
    request = payload(config, intake, snapshot)
    service = HostBackfillService(core.database)
    before = core.repository.get(intake.intake_id, "CAND_DEMO")
    for change in (
        dict(candidate_id="CAND_OTHER"),
        dict(row_id="unresolved"),
        dict(snapshot={**request["snapshot"], "attempt_id": None}),
    ):
        with pytest.raises(ContractValidationError):
            service.attach({**request, **change}, now=NOW + timedelta(seconds=3))
    assert core.repository.get(intake.intake_id, "CAND_DEMO") == before
    other_core, other, _ = setup(tmp_path, number=2)
    request["snapshot"] = command(
        other, snapshot_id=snapshot.snapshot_id, observation_id="REREAD", attempt_id="READ_BACKFILL"
    )
    with pytest.raises(ContractValidationError):
        HostBackfillService(other_core.database).attach(request, now=NOW + timedelta(seconds=3))
    assert core.repository.get(intake.intake_id, "CAND_DEMO") == before


def test_interrupted_after_intake_commit_resumes_stable_event_then_sync(tmp_path, monkeypatch):
    from jobagent.storage.pipeline_sync import PipelineSyncService

    core, intake, snapshot, pipeline, _, config = migrated(tmp_path)
    real_attempt(core, intake, snapshot)
    request = payload(config, intake, snapshot)
    original = PipelineSyncService.sync
    with monkeypatch.context() as patch:
        patch.setattr(
            PipelineSyncService,
            "sync",
            lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("interrupted")),
        )
        with pytest.raises(RuntimeError, match="interrupted"):
            HostBackfillService(core.database).attach(request, now=NOW + timedelta(seconds=3))
    assert core.repository.get(intake.intake_id, "CAND_DEMO").snapshot_id == snapshot.snapshot_id
    monkeypatch.setattr(PipelineSyncService, "sync", original)
    result = HostBackfillService(core.database).attach(request, now=NOW + timedelta(seconds=4))
    actual, _ = PipelineRepository(core.database).get(pipeline.pipeline_id, "CAND_DEMO")
    assert result["full_jd_text_stored"] and actual.jd_text == snapshot.jd_text


def test_terminal_round_rejects_before_intake_writes(tmp_path):
    core, intake, snapshot, pipeline, meta, config = migrated(tmp_path)
    with core.database.connect() as connection, connection:
        PipelineRepository.write_job(
            connection, pipeline.model_copy(update={"pipeline_state": "abandoned"}), meta
        )
    before = core.repository.get(intake.intake_id, "CAND_DEMO")
    with pytest.raises(ContractValidationError):
        HostBackfillService(core.database).attach(payload(config, intake, snapshot), now=NOW)
    assert core.repository.get(intake.intake_id, "CAND_DEMO") == before


def test_already_bound_pipeline_hook_can_advance_before_explicit_sync(tmp_path):
    core, intake, snapshot, pipeline, meta, config = migrated(tmp_path)
    with core.database.connect() as connection, connection:
        PipelineRepository.write_job(
            connection, pipeline, meta.model_copy(update={"intake_id": intake.intake_id})
        )
    real_attempt(core, intake, snapshot)
    result = HostBackfillService(core.database).attach(
        payload(config, intake, snapshot), now=NOW + timedelta(seconds=3)
    )
    actual, metadata = PipelineRepository(core.database).get(pipeline.pipeline_id, "CAND_DEMO")
    assert result["full_jd_text_stored"] and actual.jd_text == snapshot.jd_text
    assert metadata.version >= meta.version + 2  # Automatic hook, then adapter's stable sync.


def test_interrupted_after_sync_before_link_replays_original_sync_cas(tmp_path, monkeypatch):
    import sqlite3
    from contextlib import contextmanager

    core, intake, snapshot, pipeline, _, config = migrated(tmp_path)
    real_attempt(core, intake, snapshot)
    request = payload(config, intake, snapshot)
    original_connect = Database.connect

    class FailingConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if sql.startswith("INSERT INTO pipeline_backfill_links"):
                raise RuntimeError("link interrupted")
            return super().execute(sql, parameters)

    @contextmanager
    def fail_link(self):
        # sqlite's default connection context alone would not close the handle.
        connection = sqlite3.connect(self.path, factory=FailingConnection)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    with monkeypatch.context() as patch:
        patch.setattr(Database, "connect", fail_link)
        with pytest.raises(RuntimeError, match="link interrupted"):
            HostBackfillService(core.database).attach(request, now=NOW + timedelta(seconds=3))
    actual, meta = PipelineRepository(core.database).get(pipeline.pipeline_id, "CAND_DEMO")
    assert actual.jd_text == snapshot.jd_text
    monkeypatch.setattr(Database, "connect", original_connect)
    result = HostBackfillService(core.database).attach(request, now=NOW + timedelta(seconds=4))
    assert result["full_jd_text_stored"]
    assert (
        PipelineRepository(core.database).get(pipeline.pipeline_id, "CAND_DEMO")[1].version
        == meta.version
    )


def test_same_named_legacy_run_keeps_old_dispatch_and_candidate_isolation(tmp_path, monkeypatch):
    core, intake, snapshot, _, _, config = migrated(tmp_path)
    with core.database.connect() as connection, connection:
        # Synthetic old manifest is enough to test dispatch; original legacy validation remains.
        connection.execute(
            "INSERT INTO host_migration_runs VALUES (?, ?, ?, ?, ?)",
            (config.migration_id, "CAND_OTHER", "sha256:" + "a" * 64, "sha256:" + "b" * 64, "{}"),
        )
    monkeypatch.setattr(
        "jobagent.storage.pipeline_backfill.PipelineBackfillService.plan",
        lambda *_a, **_kw: pytest.fail("Matching old migration ID must take priority"),
    )
    monkeypatch.setattr(
        "jobagent.storage.pipeline_backfill.PipelineBackfillService.attach",
        lambda *_a, **_kw: pytest.fail("Wrong candidate must not fall through to new migration"),
    )
    with pytest.raises(ContractValidationError):
        HostBackfillService(core.database).plan(config.migration_id, "CAND_DEMO")
    with pytest.raises(ContractValidationError):
        HostBackfillService(core.database).attach(payload(config, intake, snapshot), now=NOW)
