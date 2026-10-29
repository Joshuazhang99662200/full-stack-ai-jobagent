import pytest

from jobagent.errors import ContractValidationError
from tests.storage.test_job_intake_service import NOW, command, draft_payload, setup


def fixture(tmp_path):
    from jobagent.storage.pipeline_service import PipelineService

    intake, row, snap = setup(tmp_path)
    row = intake.attach_snapshot(command(row, snapshot_id=snap.snapshot_id), now=NOW)
    pipeline = PipelineService(intake.database)
    pair = pipeline.create(
        dict(
            event_id="PIPE_ENTRY",
            candidate_id=row.candidate_id,
            normalized_job_id=row.job_id,
            intake_id=row.intake_id,
            evidence_reference="OWNER_LINK",
            salary_minimum_k=18,
        ),
        now=NOW,
    )
    return intake, row, pair


def test_actual_intake_draft_automatically_updates_bound_pipeline_once(tmp_path):
    from jobagent.storage.pipeline_repository import PipelineRepository

    intake, row, pair = fixture(tmp_path)
    repo = PipelineRepository(intake.database)
    data = draft_payload(row)
    changed = intake.submit_draft(data, now=NOW)
    job, meta = repo.get(pair[0].pipeline_id, row.candidate_id)
    assert job.draft_greeting == changed.draft.text
    assert meta.source_intake_version == changed.version
    version = meta.version
    assert intake.submit_draft(data, now=NOW).version == changed.version
    intake.synchronize(row.intake_id, row.candidate_id, now=NOW)
    assert repo.get(job.pipeline_id, row.candidate_id)[1].version == version


def test_recovery_after_intake_commit_finishes_missing_pipeline_sync(tmp_path, monkeypatch):
    from jobagent.storage.pipeline_repository import PipelineRepository
    from jobagent.storage.pipeline_sync import PipelineSyncService

    intake, row, pair = fixture(tmp_path)
    original = PipelineSyncService.sync

    def interrupted(*_args, **_kwargs):
        raise ContractValidationError("Synthetic interruption after source commit.")

    monkeypatch.setattr(PipelineSyncService, "sync", interrupted)
    with pytest.raises(ContractValidationError):
        intake.submit_draft(draft_payload(row), now=NOW)
    saved = intake.repository.get(row.intake_id, row.candidate_id)
    assert saved.draft is not None
    monkeypatch.setattr(PipelineSyncService, "sync", original)
    intake.synchronize(row.intake_id, row.candidate_id, now=NOW)
    assert (
        PipelineRepository(intake.database)
        .get(pair[0].pipeline_id, row.candidate_id)[0]
        .draft_greeting
        == saved.draft.text
    )
