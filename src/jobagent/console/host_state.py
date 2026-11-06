# ruff: noqa: RUF001  -- user-facing receipts are written in Chinese.
"""Read-only HostState for the panel: greeting materials and the panel's own decisions.

The repository produces only what it owns: per contact, the exact first-greeting
materials (revision = item digest, the same value `console materials` returns)
and every saved panel decision with the event id its receipt carried. Todos,
channels and execution batches belong to the host, so they are left empty and
`sync` says so instead of implying there is nothing to do.
"""

from pathlib import Path

from jobagent.bridge.panel_decisions import open_items, owned_evidence, receipt_message
from jobagent.schemas.console_host import (
    HostJob,
    HostMaterial,
    HostReceipt,
    HostState,
    HostSync,
)
from jobagent.storage.database import Database
from jobagent.storage.feedback_repository import panel_events
from jobagent.storage.outreach_repository import SqliteOutreachRepository
from jobagent.storage.pipeline_repository import PipelineRepository


def host_state(database: Path, candidate_id: str) -> HostState:
    db = Database(database)
    owned = owned_evidence(db, candidate_id)
    batches = SqliteOutreachRepository(db).list_batches()
    with db.connect() as connection:
        events = panel_events(connection, candidate_id)
    jobs = []
    for job, meta in PipelineRepository(db).list_records(candidate_id):
        if meta.normalized_job_id is None:
            continue
        open_digests = {
            item.item_digest for _, _, item in open_items(db, candidate_id, meta.normalized_job_id)
        }
        seen: set[str] = set()
        materials = []
        for batch in sorted(batches, key=lambda b: (b.created_at, b.batch_id)):
            for item in batch.items:
                if (item.job_id != meta.normalized_job_id or item.item_digest in seen
                        or not item.evidence_ids or not set(item.evidence_ids) <= owned):
                    continue
                seen.add(item.item_digest)
                materials.append(HostMaterial(
                    revision=item.item_digest, label=f"首条招呼（清单第 {item.number} 条）",
                    body=item.text, attachments=[],
                ))
        # The material still awaiting a decision is the current one, so it goes last.
        materials.sort(key=lambda m: m.revision in open_digests)
        jobs.append(HostJob(
            job_id=job.job_id, contact_id=job.pipeline_id, materials=materials,
            events=[e for e in events if e.contact_id == job.pipeline_id],
            blockers=[], progress=None, intake_at=job.entered_at,
        ))
    return HostState(
        candidate_id=candidate_id, jobs=jobs, todos=[], channels=[], batches=[],
        receipts=[
            HostReceipt(
                operation_key=e.operation_key, status="saved", event_id=e.event_id,
                message=receipt_message(e.kind),
            )
            for e in events
        ],
        sync=HostSync(
            status="unavailable", checked_at=None, differences=[],
            message="仓库只导出首条招呼材料与面板决定；待办、渠道与执行批次由宿主提供。",
        ),
    )
