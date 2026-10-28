"""Plan private JD backfills and append lineage only after the existing intake gate."""

import json
from datetime import datetime

from jobagent.jobs.jd_snapshot import canonical_digest
from jobagent.jobs.job_intake import reject
from jobagent.schemas.host_migration import LegacyBackfillBinding, LegacyPartialSnapshot
from jobagent.storage.database import Database
from jobagent.storage.host_migration import HostQueueMigrator
from jobagent.storage.job_intake_service import JobIntakeService


class HostBackfillService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.core = JobIntakeService(database)

    def plan(
        self, migration_id: str, candidate_id: str, priority_ids: list[str] | None = None
    ) -> dict[str, object]:
        manifest = HostQueueMigrator().verify(self.database.path, migration_id)
        if manifest["candidate_id"] != candidate_id:
            reject("Migration belongs to another candidate.")
        priorities = priority_ids if priority_ids is not None else manifest["priority_ids"]
        assert isinstance(priorities, list)
        order = {str(value): i for i, value in enumerate(priorities)}
        with self.database.connect() as connection:
            saved = connection.execute(
                "SELECT * FROM host_legacy_rows WHERE migration_id = ? ORDER BY ordinal",
                (migration_id,),
            ).fetchall()
        rows = []
        for old in saved:
            current = self.core.repository.get(old["intake_id"], candidate_id)
            while current.merged_into:
                current = self.core.repository.get(current.merged_into, candidate_id)
            complete = False
            if current.snapshot_id and current.job_id:
                snapshot = self.core.knowledge.get(current.snapshot_id)
                latest = self.core.knowledge.list_snapshots(current.job_id)[-1]
                job = self.core.jobs.get_job(current.job_id)
                complete = (
                    latest.snapshot_id == snapshot.snapshot_id
                    and snapshot.completeness == "full"
                    and job is not None
                    and job.jd_raw.strip() == snapshot.jd_text.strip()
                )
            partial = LegacyPartialSnapshot.model_validate_json(old["legacy_snapshot_json"])
            rows.append(
                {
                    "row_id": old["row_id"],
                    "intake_id": current.intake_id,
                    "expected_version": current.version,
                    "job_url": old["job_url"],
                    "source_job_id": old["source_job_id"],
                    "platform": old["platform"],
                    "legacy_snapshot_id": partial.legacy_snapshot_id,
                    "legacy_snapshot_version": 0,
                    "snapshot_id": current.snapshot_id,
                    "status": "snapshot_complete" if complete else "partial_not_in_strategy",
                    "full_jd_text_stored": complete,
                }
            )
        rows.sort(
            key=lambda row: (
                order.get(str(row["row_id"]), len(order)),
                next(i for i, old in enumerate(saved) if old["row_id"] == row["row_id"]),
            )
        )
        known = {row["row_id"] for row in rows}
        return {
            "migration_id": migration_id,
            "candidate_id": candidate_id,
            "rows": rows,
            "unknown_priority_ids": [str(i) for i in priorities if str(i) not in known],
        }

    def attach(self, data: dict[str, object], *, now: datetime) -> dict[str, object]:
        request = LegacyBackfillBinding.model_validate(data)
        digest = canonical_digest(request.model_dump(mode="json"))
        with self.database.connect() as connection:
            old = connection.execute(
                "SELECT * FROM host_backfill_links WHERE event_id = ?", (request.snapshot.event_id,)
            ).fetchone()
            row = connection.execute(
                "SELECT r.*, m.candidate_id FROM host_legacy_rows r "
                "JOIN host_migration_runs m ON m.migration_id = r.migration_id "
                "WHERE r.migration_id = ? AND r.row_id = ?",
                (request.migration_id, request.row_id),
            ).fetchone()
        if old:
            if old["input_digest"] != digest or old["candidate_id"] != request.candidate_id:
                reject("Backfill event ID has different evidence.")
            result: dict[str, object] = json.loads(old["link_json"])
            return result
        if row is None or row["candidate_id"] != request.candidate_id:
            reject("Legacy row not found for this candidate.")
        command = request.snapshot
        current = self.core.repository.get(row["intake_id"], request.candidate_id)
        while current.merged_into:
            current = self.core.repository.get(current.merged_into, request.candidate_id)
        if command.candidate_id != request.candidate_id or command.intake_id != current.intake_id:
            reject("Backfill command must bind the original row's canonical intake.")
        if not command.observation_id or not command.attempt_id:
            reject(
                "Backfill requires the actual new read observation and completed budget attempt."
            )
        updated = self.core.attach_snapshot(command.model_dump(), now=now)
        snapshot = self.core.knowledge.get(updated.snapshot_id or "")
        observation = next(
            d
            for d in self.core.knowledge.discoveries(snapshot.job_id)
            if d.observation_id == command.observation_id
        )
        partial = LegacyPartialSnapshot.model_validate_json(row["legacy_snapshot_json"])
        link: dict[str, object] = {
            "migration_id": request.migration_id,
            "row_id": request.row_id,
            "candidate_id": request.candidate_id,
            "intake_id": updated.intake_id,
            "legacy_snapshot_id": partial.legacy_snapshot_id,
            "legacy_snapshot_version": 0,
            "snapshot_id": snapshot.snapshot_id,
            "snapshot_version": snapshot.snapshot_version,
            "observation_id": observation.observation_id,
            "fetched_at": observation.fetched_at.isoformat(),
            "query_hit": observation.query_hit,
            "discovery_kind": observation.discovery_kind,
            "job_url": str(snapshot.job_url),
            "jd_text_hash": snapshot.jd_text_hash,
            "full_jd_text_stored": True,
        }
        with self.database.connect() as connection, connection:
            connection.execute(
                "INSERT INTO host_backfill_links VALUES (?, ?, ?, ?, ?, ?)",
                (
                    command.event_id,
                    request.candidate_id,
                    request.migration_id,
                    request.row_id,
                    digest,
                    json.dumps(link, ensure_ascii=False),
                ),
            )
        return link
