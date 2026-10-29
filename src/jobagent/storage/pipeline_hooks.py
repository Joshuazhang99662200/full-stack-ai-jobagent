"""Recoverable intake-to-pipeline artifact sync; no external actions or approvals."""

from datetime import datetime

from jobagent.jobs.jd_snapshot import canonical_digest
from jobagent.schemas.job_intake import IntakeRecord
from jobagent.storage.database import Database
from jobagent.storage.pipeline_repository import PipelineRepository
from jobagent.storage.pipeline_sync import PipelineSyncService


def sync_bound_pipelines(
    database: Database, record: IntakeRecord, *, now: datetime
) -> IntakeRecord:
    if record.closed or record.merged_into:
        return record
    with database.connect() as connection:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='pipeline_jobs'"
        ).fetchone()
        if table is None:
            return record
    repository = PipelineRepository(database)
    sync = PipelineSyncService(database)
    for job, meta in repository.list_records(record.candidate_id):
        if meta.intake_id is None or job.pipeline_state == "abandoned":
            continue
        source = sync.source(job, meta)
        if source.intake_id != record.intake_id or meta.source_intake_version == source.version:
            continue
        event_id = (
            "INTAKE_SYNC_"
            + canonical_digest([job.pipeline_id, source.intake_id, source.version])[7:39]
        )
        with database.connect() as connection:
            old = connection.execute(
                "SELECT 1 FROM pipeline_requests WHERE event_id = ?", (event_id,)
            ).fetchone()
        if old:
            continue
        sync.sync(
            dict(
                event_id=event_id,
                pipeline_id=job.pipeline_id,
                candidate_id=job.candidate_id,
                expected_version=meta.version,
            ),
            now=now,
        )
    return record
