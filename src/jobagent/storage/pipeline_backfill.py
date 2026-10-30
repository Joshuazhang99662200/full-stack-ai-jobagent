"""Append real full-JD lineage to offline pipeline adoption using the existing intake gates."""

import json
import sqlite3
from datetime import datetime
from typing import Any

from pydantic import HttpUrl

from jobagent.errors import ContractValidationError
from jobagent.jobs.jd_snapshot import canonical_digest, text_digest
from jobagent.jobs.job_intake import reject
from jobagent.schemas.host_migration import LegacyBackfillBinding
from jobagent.schemas.pipeline import PipelineJob, PipelineMeta
from jobagent.schemas.pipeline_migration import PipelineMigrationConfig
from jobagent.storage.database import Database
from jobagent.storage.job_intake_service import JobIntakeService
from jobagent.storage.pipeline_repository import PipelineRepository
from jobagent.storage.pipeline_sync import PipelineSyncService


class PipelineBackfillService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.core = JobIntakeService(database)
        self.repository = PipelineRepository(database)
        self.sync = PipelineSyncService(database)

    def rows(
        self, migration_id: str, candidate_id: str
    ) -> tuple[PipelineMigrationConfig, list[sqlite3.Row]]:
        with self.database.connect() as connection:
            run = connection.execute(
                "SELECT * FROM pipeline_migration_runs WHERE migration_id = ?", (migration_id,)
            ).fetchone()
            rows = connection.execute(
                "SELECT * FROM pipeline_migration_rows WHERE migration_id = ? ORDER BY ordinal",
                (migration_id,),
            ).fetchall()
        if run is None or run["candidate_id"] != candidate_id:
            reject("Pipeline migration not found for this candidate.")
        manifest = json.loads(run["manifest_json"])
        config = PipelineMigrationConfig.model_validate(manifest["config"])
        if config.candidate_id != candidate_id or config.migration_id != migration_id:
            reject("Migration configuration belongs to a different candidate or source.")
        if [r["row_id"] for r in rows] != config.expected_row_ids:
            reject("Original migration row identities changed.")
        for row in rows:
            if text_digest(row["source_line"]) != row["source_digest"]:
                reject("Original migration source evidence changed.")
        return config, rows

    @staticmethod
    def identity(
        row: sqlite3.Row, config: PipelineMigrationConfig
    ) -> tuple[str, str | None, str | None]:
        raw: dict[str, Any] = json.loads(row["source_line"])
        fields = config.fields
        if str(raw.get(fields.row_id)) != row["row_id"]:
            reject("Original row ID no longer matches its preserved source.")
        candidate = raw.get(fields.candidate_id)
        if candidate is not None and candidate != config.candidate_id:
            reject("Original source belongs to a different candidate.")
        source = str(raw.get(fields.platform, ""))
        platform = config.platform_values.get(source, source)
        url = raw.get(fields.job_url)
        provider = raw.get(fields.source_job_id)
        provider = str(provider) if provider is not None else None
        if url and config.job_id_mode == "preserve":
            prefix = config.job_id_prefixes.get(platform)
            original_id = raw.get(fields.job_id)
            if not prefix or not isinstance(original_id, str) or not original_id.startswith(prefix):
                reject("Original provider identity needs its explicit platform prefix.")
            actual = original_id[len(prefix) :]
            if not actual or (provider is not None and provider != actual):
                reject("Original provider identities disagree.")
            provider = actual
        return platform, str(HttpUrl(url)) if url else None, provider

    def bound(
        self, row: sqlite3.Row, config: PipelineMigrationConfig
    ) -> tuple[PipelineJob, PipelineMeta]:
        if row["pipeline_id"] is None:
            reject("Legacy identity is unverified; resolve it before pipeline backfill.")
        job, meta = self.repository.get(row["pipeline_id"], config.candidate_id)
        platform, url, provider = self.identity(row, config)
        raw = json.loads(row["source_line"])
        expected_job_id = (
            raw.get(config.fields.job_id)
            if config.job_id_mode == "preserve"
            else platform + "-" + (provider or "")
        )
        if (
            job.job_id != expected_job_id
            or job.platform != platform
            or str(job.job_url) != url
            or not provider
            or meta.source_job_id != provider
            or job.title != raw.get(config.fields.title)
            or job.company != raw.get(config.fields.company)
            or meta.domain != config.domain
        ):
            reject("Pipeline target differs from its original migration source.")
        return job, meta

    def plan(
        self, migration_id: str, candidate_id: str, priority_ids: list[str] | None = None
    ) -> dict[str, object]:
        config, saved = self.rows(migration_id, candidate_id)
        priorities = priority_ids or []
        order = {str(value): i for i, value in enumerate(priorities)}
        rows: list[dict[str, object]] = []
        for old in saved:
            platform, url, provider = self.identity(old, config)
            complete = False
            intake_id, version, snapshot_id, pipeline_version = old["intake_id"], None, None, None
            if old["pipeline_id"]:
                job, meta = self.bound(old, config)
                pipeline_version = meta.version
                try:
                    source = self.sync.source(job, meta)
                except ContractValidationError:
                    source = None
                if source:
                    intake_id, version = source.intake_id, source.version
                if meta.intake_id and source:
                    _source, changes, _extra, _digest = self.sync.artifacts(
                        job, meta, now=max(job.updated_at, source.updated_at)
                    )
                    complete = bool(
                        changes["jd_text"]
                        and job.jd_text == changes["jd_text"]
                        and meta.snapshot_id == source.snapshot_id
                    )
                    snapshot_id = source.snapshot_id if complete else None
            rows.append(
                dict(
                    row_id=old["row_id"],
                    pipeline_id=old["pipeline_id"],
                    intake_id=intake_id,
                    expected_version=version,
                    pipeline_version=pipeline_version,
                    platform=platform,
                    job_url=url,
                    source_job_id=provider,
                    legacy_snapshot_id=old["source_digest"],
                    legacy_source_digest=old["source_digest"],
                    legacy_snapshot_version=0,
                    snapshot_id=snapshot_id,
                    identity_unverified=old["pipeline_id"] is None,
                    status=(
                        "identity_unverified"
                        if old["pipeline_id"] is None
                        else "full"
                        if complete
                        else "partial_not_in_strategy"
                    ),
                    full_jd_text_stored=complete,
                )
            )
        rows.sort(key=lambda row: order.get(str(row["row_id"]), len(order)))
        known = {row["row_id"] for row in rows}
        return dict(
            migration_id=migration_id,
            candidate_id=candidate_id,
            rows=rows,
            priority_ids=priorities,
            unknown_priority_ids=[str(value) for value in priorities if str(value) not in known],
        )

    def attach(self, data: dict[str, object], *, now: datetime) -> dict[str, object]:
        request = LegacyBackfillBinding.model_validate(data)
        digest = canonical_digest(request.model_dump(mode="json"))
        command = request.snapshot
        with self.database.connect() as connection:
            previous = connection.execute(
                "SELECT * FROM pipeline_backfill_links WHERE event_id = ?", (command.event_id,)
            ).fetchone()
        if previous:
            if (
                previous["input_digest"] != digest
                or previous["candidate_id"] != request.candidate_id
            ):
                reject("Backfill event ID cannot change its original input or candidate.")
            result: dict[str, object] = json.loads(previous["link_json"])
            return result
        config, rows = self.rows(request.migration_id, request.candidate_id)
        original = next((row for row in rows if row["row_id"] == request.row_id), None)
        if original is None:
            reject("Original migration row not found.")
        job, meta = self.bound(original, config)
        if job.pipeline_state == "abandoned":
            reject("Abandoned contact rounds cannot accept new artifact bindings.")
        source = self.sync.source(job, meta)
        if command.candidate_id != request.candidate_id or command.intake_id != source.intake_id:
            reject("Backfill must bind the original target's exact canonical intake.")
        if source.closed or source.merged_into:
            reject("Backfill requires an active canonical intake.")
        if not command.observation_id or not command.attempt_id:
            reject("Backfill requires a real read observation and completed budget attempt.")
        updated = self.core.attach_snapshot(command.model_dump(), now=now)
        snapshot = self.core.knowledge.get(updated.snapshot_id or "")
        observation = next(
            d
            for d in self.core.knowledge.discoveries(snapshot.job_id)
            if d.observation_id == command.observation_id
        )
        # The intake hook may already have advanced a previously bound pipeline.
        # After an interrupted sync/link boundary, reuse the stable sync event's original CAS.
        sync_event = "BACKFILL_SYNC_" + digest[7:39]
        with self.database.connect() as connection:
            saved_sync = connection.execute(
                "SELECT * FROM pipeline_requests WHERE event_id = ?", (sync_event,)
            ).fetchone()
        _, current_meta = self.repository.get(job.pipeline_id, request.candidate_id)
        expected_version = current_meta.version
        if saved_sync:
            if (
                saved_sync["candidate_id"] != request.candidate_id
                or saved_sync["pipeline_id"] != job.pipeline_id
            ):
                reject("Backfill sync event belongs to a different target.")
            expected_version = json.loads(saved_sync["response_json"])["meta"]["version"] - 1
        synced, metadata = self.sync.sync(
            dict(
                event_id=sync_event,
                pipeline_id=job.pipeline_id,
                candidate_id=request.candidate_id,
                expected_version=expected_version,
            ),
            now=now,
        )
        if (
            metadata.snapshot_id != snapshot.snapshot_id
            or synced.jd_text_hash != snapshot.jd_text_hash
        ):
            reject("Pipeline did not bind the validated full snapshot.")
        link: dict[str, object] = dict(
            migration_id=request.migration_id,
            row_id=request.row_id,
            candidate_id=request.candidate_id,
            pipeline_id=job.pipeline_id,
            intake_id=updated.intake_id,
            legacy_snapshot_id=original["source_digest"],
            legacy_source_digest=original["source_digest"],
            legacy_snapshot_version=0,
            snapshot_id=snapshot.snapshot_id,
            snapshot_version=snapshot.snapshot_version,
            observation_id=observation.observation_id,
            fetched_at=observation.fetched_at.isoformat(),
            query_hit=None,
            discovery_kind="manual",
            job_url=str(snapshot.job_url),
            source_job_id=source.source_job_id,
            jd_text_hash=snapshot.jd_text_hash,
            full_jd_text_stored=True,
        )
        with self.database.connect() as connection, connection:
            connection.execute(
                "INSERT INTO pipeline_backfill_links VALUES (?, ?, ?, ?, ?, ?)",
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
