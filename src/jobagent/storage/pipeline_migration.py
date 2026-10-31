"""Offline private adoption into pipeline truth; legacy declarations never become proofs."""

import hashlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, HttpUrl, TypeAdapter, ValidationError

from jobagent.errors import ContractValidationError
from jobagent.jobs.jd_snapshot import canonical_digest, text_digest
from jobagent.jobs.job_intake import public_state, reject
from jobagent.schemas.job_intake import IntakeRequest
from jobagent.schemas.pipeline import PipelineHistory, PipelineJob, PipelineMeta
from jobagent.schemas.pipeline_migration import PipelineMappedLegacyRow, PipelineMigrationConfig
from jobagent.storage.database import Database
from jobagent.storage.host_migration import (
    HostQueueMigrator,
    atomic_text,
    backup_database,
    file_digest,
)
from jobagent.storage.job_intake_service import JobIntakeService
from jobagent.storage.pipeline_repository import PipelineRepository
from jobagent.storage.pipeline_service import salary_fields


def migration_database_digest(path: Path) -> str:
    """Hash schema and facts, excluding only this manifest's self-referential post digest."""
    hasher = hashlib.sha256()
    with Database(path).connect() as connection:
        hasher.update(str(connection.execute("PRAGMA user_version").fetchone()[0]).encode())
        schema = connection.execute(
            "SELECT type, name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()
        for entry in schema:
            hasher.update(repr(tuple(entry)).encode("utf-8"))
            if entry["type"] != "table":
                continue
            name = entry["name"].replace('"', '""')
            values = []
            for saved in connection.execute(f'SELECT * FROM "{name}"').fetchall():
                if entry["name"] == "pipeline_migration_runs":
                    manifest = json.loads(saved["manifest_json"])
                    manifest.pop("post_database_digest", None)
                    value = (*tuple(saved)[:-1], json.dumps(manifest, sort_keys=True))
                else:
                    value = tuple(saved)
                values.append(repr(value))
            for serialized in sorted(values):
                hasher.update(serialized.encode("utf-8"))
    return "sha256:" + hasher.hexdigest()


def scalar(raw: dict[str, object], field: str) -> str | None:
    value = raw.get(field)
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, str | int):
        reject("Mapped legacy scalar must be a string or original numeric ID.")
    return str(value)


class PipelineMigrator:
    def inspect(self, source: Path) -> dict[str, object]:
        rows = HostQueueMigrator.raw_rows(source)
        return {
            "rows": len(rows),
            "fields": sorted({field for _, raw in rows for field in raw}),
            "source_digest": file_digest(source),
            "values_exposed": False,
        }

    def mapped_rows(
        self, source: Path, config: PipelineMigrationConfig, *, now: datetime
    ) -> list[PipelineMappedLegacyRow]:
        raw_rows = HostQueueMigrator.raw_rows(source)
        if len(raw_rows) != config.expected_count:
            reject("Legacy row count differs from the private migration configuration.")
        result = []
        for line, raw in raw_rows:
            fields = config.fields
            for field in (
                fields.title,
                fields.company,
                fields.location,
                fields.salary_raw,
                fields.jd_summary,
                fields.draft_greeting,
                fields.draft_version,
                fields.draft_digest,
            ):
                if raw.get(field) is not None and not isinstance(raw[field], str):
                    reject("Legacy descriptive fields must preserve their original text.")
            original_id = scalar(raw, fields.row_id)
            candidate = scalar(raw, fields.candidate_id)
            if original_id is None or (candidate is not None and candidate != config.candidate_id):
                reject("Original row ID is missing or candidate identity differs.")
            platform = scalar(raw, fields.platform) or ""
            platform = config.platform_values.get(platform, platform)
            if platform not in {"boss", "zhaopin"}:
                reject("Legacy board needs an explicit supported platform mapping.")
            link = scalar(raw, fields.job_url)
            url = HttpUrl(link) if link else None
            title, company = scalar(raw, fields.title), scalar(raw, fields.company)
            provider = scalar(raw, fields.source_job_id)
            job_id = scalar(raw, fields.job_id)
            if url is not None:
                if config.job_id_mode == "platform_source_id":
                    if provider is None:
                        reject("Canonical ID mapping needs the actual provider job ID.")
                    job_id = platform + "-" + provider
                else:
                    prefix = config.job_id_prefixes.get(platform)
                    if not job_id or not prefix or not job_id.startswith(prefix):
                        reject("Preserved job ID needs its explicitly configured platform prefix.")
                    extracted = job_id[len(prefix) :]
                    if not extracted or (provider is not None and provider != extracted):
                        reject("Preserved and provider job identities disagree.")
                    provider = extracted
                if not job_id or not title or not company:
                    reject("Resolved legacy rows require real job ID, title and company.")
            points = raw.get(fields.jd_points)
            if points is None:
                summary = scalar(raw, fields.jd_summary)
                points = [summary] if summary is not None else []
            if (
                not isinstance(points, list)
                or len(points) > 3
                or not all(isinstance(p, str) for p in points)
            ):
                reject("Legacy JD points must contain at most three actual excerpts.")
            entered_raw = raw.get(fields.entered_at)
            entered: datetime | None = TypeAdapter(AwareDatetime | None).validate_python(
                entered_raw
            )
            basis: Literal["observed", "derived", "unknown_legacy"] = (
                "observed" if entered else "unknown_legacy"
            )
            reference = "SOURCE_" + text_digest(line)[7:]
            if entered is None:
                entered = config.derived_entered_at_by_row.get(
                    original_id, config.derived_entered_at
                )
                if entered is not None:
                    basis = "derived"
                    reference = config.derived_evidence_reference or ""
            if (entered is None and url is not None) or (entered is not None and entered > now):
                reject(
                    "Legacy entry time must be actual or explicitly derived, never invented "
                    "or future."
                )
            draft = scalar(raw, fields.draft_greeting)
            draft_hash = scalar(raw, fields.draft_digest)
            if draft_hash is not None and (draft is None or text_digest(draft) != draft_hash):
                reject("Legacy draft does not match its supplied exact digest.")
            result.append(
                PipelineMappedLegacyRow.model_validate(
                    dict(
                        row_id=original_id,
                        platform=platform,
                        job_id=job_id,
                        provider_id=provider,
                        job_url=url,
                        title=title,
                        company=company,
                        location=scalar(raw, fields.location),
                        salary_raw=scalar(raw, fields.salary_raw) or "",
                        jd_points=points,
                        draft_greeting=draft,
                        draft_version=scalar(raw, fields.draft_version),
                        entered_at=entered,
                        entered_time_basis=basis,
                        entry_evidence_reference=reference,
                        source_line=line,
                        source_digest=text_digest(line),
                        source_json=raw,
                    )
                )
            )
        if [row.row_id for row in result] != config.expected_row_ids:
            reject("Original row IDs or ordering differ; no rows are renumbered.")
        targets = [row for row in result if row.job_url is not None]
        keys = [(r.platform, r.provider_id) for r in targets]
        urls = [(r.platform, str(r.job_url)) for r in targets]
        if len(set(keys)) != len(keys) or len(set(urls)) != len(urls):
            reject("Multiple legacy IDs resolve to the same or conflicting source target.")
        return result

    def manifest(
        self, database: Path, migration_id: str, *, candidate_id: str | None = None
    ) -> dict[str, object]:
        with Database(database).connect() as connection:
            row = connection.execute(
                "SELECT * FROM pipeline_migration_runs WHERE migration_id = ?", (migration_id,)
            ).fetchone()
        if row is None:
            reject("Pipeline migration not found.")
        result: dict[str, object] = json.loads(row["manifest_json"])
        if candidate_id is not None and row["candidate_id"] != candidate_id:
            reject("Pipeline migration belongs to another candidate.")
        if (
            result.get("candidate_id") != row["candidate_id"]
            or canonical_digest(result.get("config")) != row["config_digest"]
            or result.get("source_digest") != row["source_digest"]
        ):
            reject("Pipeline migration manifest bindings differ from their original values.")
        return result

    def migrate(
        self, source: Path, database: Path, config: PipelineMigrationConfig, *, now: datetime
    ) -> dict[str, object]:
        source, database = source.resolve(), database.resolve()
        try:
            config = PipelineMigrationConfig.model_validate(config.model_dump())
            rows = self.mapped_rows(source, config, now=now)
        except (ValidationError, ValueError) as error:
            raise ContractValidationError(
                "Private pipeline migration mapping is invalid."
            ) from error
        source_hash, config_hash = (
            file_digest(source),
            canonical_digest(config.model_dump(mode="json")),
        )
        if source == database:
            reject("Original queue and target database must be different files.")
        if database.exists():
            with Database(database).connect() as connection:
                table = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE name = 'pipeline_migration_runs'"
                ).fetchone()
                previous = (
                    connection.execute(
                        "SELECT * FROM pipeline_migration_runs WHERE migration_id = ?",
                        (config.migration_id,),
                    ).fetchone()
                    if table
                    else None
                )
            if previous:
                if (
                    previous["source_digest"] != source_hash
                    or previous["config_digest"] != config_hash
                ):
                    reject("Migration ID cannot change its source bytes or explicit mapping.")
                return {
                    **self.verify(database, config.migration_id, candidate_id=config.candidate_id),
                    "replayed": True,
                }
        if any(Path(str(database) + suffix).exists() for suffix in ("-wal", "-journal")):
            reject("Stop all writers and checkpoint journals before offline migration.")
        database.parent.mkdir(parents=True, exist_ok=True)
        directory = database.parent / "pipeline-migration-backups" / config.migration_id
        directory.mkdir(parents=True, exist_ok=True)
        backup, original = directory / "before.sqlite3", directory / "queue-original.jsonl"
        baseline = migration_database_digest(database) if database.exists() else None
        descriptor, name = tempfile.mkstemp(
            dir=database.parent, prefix=".pipeline-migration-", suffix=".sqlite3"
        )
        os.close(descriptor)
        temporary = Path(name)
        try:
            if database.exists():
                backup_database(database, temporary)
            Database(temporary).migrate()
            backup_source = database if database.exists() else temporary
            if backup.exists() and migration_database_digest(backup) != migration_database_digest(
                backup_source
            ):
                reject("Existing backup has a different baseline; choose a new migration ID.")
            if not backup.exists():
                backup_database(backup_source, backup)
            if original.exists() and file_digest(original) != source_hash:
                reject("Original queue backup differs; choose a new migration ID.")
            if not original.exists():
                original.write_bytes(source.read_bytes())
            manifest: dict[str, object] = dict(
                migration_id=config.migration_id,
                candidate_id=config.candidate_id,
                config=config.model_dump(mode="json"),
                source_digest=source_hash,
                source_path=str(source),
                source_backup_path=str(original),
                backup_path=str(backup),
                backup_digest=migration_database_digest(backup),
                original_database_existed=baseline is not None,
                row_ids=[r.row_id for r in rows],
                source_rows=len(rows),
                imported_at=now.isoformat(),
            )
            working = Database(temporary)
            with working.connect() as connection, connection:
                connection.execute(
                    "INSERT INTO pipeline_migration_runs VALUES (?, ?, ?, ?, ?)",
                    (
                        config.migration_id,
                        config.candidate_id,
                        source_hash,
                        config_hash,
                        json.dumps(manifest),
                    ),
                )
            repository, intake = PipelineRepository(working), JobIntakeService(working)
            if any(row.job_url is not None for row in rows):
                with working.connect() as connection, connection:
                    connection.execute(
                        "INSERT OR IGNORE INTO pipeline_authorities VALUES (?, ?, ?)",
                        (config.candidate_id, now.isoformat(), "SOURCE_" + source_hash[7:]),
                    )
            for ordinal, row in enumerate(rows):
                event_key = canonical_digest([config.migration_id, row.row_id, row.source_digest])[
                    7:
                ]
                reference = "SOURCE_" + row.source_digest[7:]
                pipeline_id, intake_id = None, None
                if row.job_url is None:
                    pending = intake.enqueue(
                        IntakeRequest(
                            request_id="PIPEMIG_" + event_key,
                            candidate_id=config.candidate_id,
                            domain=config.domain,
                            platform=row.platform,
                            message_reference=reference,
                            entry_kind="conversation_card",
                            target_reference=row.row_id,
                            source_job_id=row.provider_id,
                            occurred_at=now,
                        ),
                        now=now,
                    )
                    pending = intake.repository.update(
                        pending.intake_id,
                        config.candidate_id,
                        event_id="PARTIAL_" + event_key,
                        expected_version=pending.version,
                        kind="legacy_partial_registered",
                        changes={
                            "legacy_snapshot_id": row.source_digest,
                            "blocked_reason": "legacy_identity_unverified",
                        },
                        now=now,
                    )
                    intake_id = pending.intake_id
                else:
                    assert row.entered_at is not None and row.job_id is not None
                    pipeline_id = (
                        "PIPE_" + canonical_digest([config.candidate_id, row.job_id])[7:23].upper()
                    )
                    low, high, salary = salary_fields(
                        row.salary_raw, config.salary_currency, config.salary_minimum_k
                    )
                    draft_hash = (
                        text_digest(row.draft_greeting) if row.draft_greeting is not None else None
                    )
                    job = PipelineJob.model_validate(
                        dict(
                            pipeline_id=pipeline_id,
                            candidate_id=config.candidate_id,
                            job_id=row.job_id,
                            platform=row.platform,
                            job_url=row.job_url,
                            title=row.title,
                            company=row.company,
                            location=row.location,
                            salary_raw=row.salary_raw,
                            salary_min_k=low,
                            salary_max_k=high,
                            salary_verified=salary,
                            jd_points=json.dumps(row.jd_points, ensure_ascii=False)
                            if row.jd_points
                            else None,
                            draft_greeting=row.draft_greeting,
                            draft_version=(row.draft_version or "CONTENT_" + draft_hash[7:23])
                            if draft_hash
                            else None,
                            draft_digest=draft_hash,
                            pipeline_state="draft_pending",
                            state_reason="normal",
                            state_changed_at=row.entered_at,
                            entered_at=row.entered_at,
                            updated_at=row.entered_at,
                        )
                    )
                    cached = next(
                        (
                            j
                            for j in intake.jobs.list_jobs()
                            if j.source == row.platform
                            and j.source_job_id == row.provider_id
                            and j.url == row.job_url
                        ),
                        None,
                    )
                    meta = PipelineMeta(
                        pipeline_id=pipeline_id,
                        normalized_job_id=cached.id if cached else None,
                        source_job_id=row.provider_id,
                        domain=config.domain,
                        salary_minimum_k=config.salary_minimum_k,
                        salary_currency=config.salary_currency,
                        entered_time_basis=row.entered_time_basis,
                        entered_evidence_reference=row.entry_evidence_reference,
                    )
                    repository.create(
                        job, meta, event_id="ENTRY_" + event_key, evidence_reference=reference,
                        now=now,
                    )
                    if row.row_id in config.sent_row_ids:
                        declared = PipelineJob.model_validate(
                            {
                                **job.model_dump(),
                                "pipeline_state": "greeting_sent",
                                "state_changed_at": now,
                                "updated_at": now,
                            }
                        )
                        metadata = meta.model_copy(
                            update={
                                "proof_status": "proof_pending",
                                "version": 2,
                                "last_evidence_reference": reference,
                            }
                        )
                        with working.connect() as connection, connection:
                            repository.write_job(connection, declared, metadata, now=now)
                            repository.append_history(
                                connection,
                                PipelineHistory(
                                    history_id="PH_" + event_key[:24].upper(),
                                    pipeline_id=pipeline_id,
                                    from_state="draft_pending",
                                    to_state="greeting_sent",
                                    changed_at=now,
                                    evidence_kind="platform_state",
                                    evidence_reference=reference,
                                    reason_code="normal",
                                ),
                                now=now,
                            )
                            repository.remember(
                                connection,
                                "DECLARE_" + event_key,
                                canonical_digest(
                                    [
                                        "legacy_declaration",
                                        config.migration_id,
                                        row.row_id,
                                        row.source_digest,
                                    ]
                                ),
                                (declared, metadata),
                            )
                with working.connect() as connection, connection:
                    connection.execute(
                        "INSERT INTO pipeline_migration_rows "
                        "(migration_id,row_id,ordinal,pipeline_id,intake_id,"
                        "source_digest,source_line) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            config.migration_id,
                            row.row_id,
                            ordinal,
                            pipeline_id,
                            intake_id,
                            row.source_digest,
                            row.source_line,
                        ),
                    )
            with working.connect() as connection, connection:
                connection.execute(
                    "UPDATE pipeline_migration_runs SET manifest_json = ? WHERE migration_id = ?",
                    (json.dumps(manifest), config.migration_id),
                )
            manifest["post_database_digest"] = migration_database_digest(temporary)
            with working.connect() as connection, connection:
                connection.execute(
                    "UPDATE pipeline_migration_runs SET manifest_json = ? WHERE migration_id = ?",
                    (json.dumps(manifest), config.migration_id),
                )
            result = self.verify(temporary, config.migration_id, candidate_id=config.candidate_id)
            if file_digest(source) != source_hash or (
                database.exists() and migration_database_digest(database) != baseline
            ):
                reject("Source or database changed during staging; no activation was performed.")
            temporary.replace(database)
            return {**result, "replayed": False}
        finally:
            temporary.unlink(missing_ok=True)

    def verify(
        self, database: Path, migration_id: str, *, candidate_id: str | None = None
    ) -> dict[str, object]:
        manifest = self.manifest(database, migration_id, candidate_id=candidate_id)
        config = PipelineMigrationConfig.model_validate(manifest["config"])
        original = Path(str(manifest["source_backup_path"]))
        if file_digest(original) != manifest["source_digest"]:
            reject("Original queue backup no longer matches its immutable source hash.")
        mapped = self.mapped_rows(
            original, config, now=datetime.fromisoformat(str(manifest["imported_at"]))
        )
        repository = PipelineRepository(Database(database))
        with repository.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM pipeline_migration_rows WHERE migration_id = ? ORDER BY ordinal",
                (migration_id,),
            ).fetchall()
        if [r["row_id"] for r in rows] != manifest["row_ids"] or len(rows) != len(mapped):
            reject("Migrated original IDs or row count differ.")
        pending, deferred, pipelines = 0, [], []
        for source, saved in zip(mapped, rows, strict=True):
            if (
                source.source_digest != saved["source_digest"]
                or source.source_line != saved["source_line"]
                or text_digest(saved["source_line"]) != saved["source_digest"]
            ):
                reject("Original row evidence was changed after migration.")
            if saved["pipeline_id"] is None:
                if source.job_url is not None or not saved["intake_id"]:
                    reject("Resolved and deferred legacy identity bindings differ.")
                JobIntakeService(repository.database).repository.get(
                    saved["intake_id"], config.candidate_id
                )
                deferred.append(source.row_id)
                continue
            job, meta = repository.get(saved["pipeline_id"], config.candidate_id)
            if (
                job.job_id != source.job_id
                or job.platform != source.platform
                or job.job_url != source.job_url
                or job.title != source.title
                or job.company != source.company
            ):
                reject("A migrated job ID, URL, title or company differs from its source.")
            pipelines.append(job.pipeline_id)
            pending += meta.proof_status == "proof_pending"
        return {
            **manifest,
            "valid": True,
            "pipeline_rows": len(pipelines),
            "deferred_row_ids": deferred,
            "deferred_send_claim_row_ids": [r for r in deferred if r in config.sent_row_ids],
            "proof_pending": pending,
            "state_authority": "pipeline_jobs",
        }

    def project(
        self, database: Path, migration_id: str, output: Path, *, candidate_id: str | None = None
    ) -> dict[str, object]:
        manifest = self.verify(database, migration_id, candidate_id=candidate_id)
        protected = {
            database.resolve(),
            *(
                Path(str(manifest[k])).resolve()
                for k in ("source_path", "source_backup_path", "backup_path")
            ),
        }
        if output.resolve() in protected:
            reject("Projection cannot overwrite source, database or immutable backups.")
        candidate = str(manifest["candidate_id"])
        repository = PipelineRepository(Database(database))
        form = {str(row["pipeline_id"]): row for row in repository.form(candidate)}
        with repository.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM pipeline_migration_rows WHERE migration_id = ? ORDER BY ordinal",
                (migration_id,),
            ).fetchall()
        projected = []
        for row in rows:
            if row["pipeline_id"]:
                runtime = dict(form[row["pipeline_id"]])
                full = runtime["jd_text"] is not None
                runtime.update(
                    snapshot_state="snapshot_complete" if full else "snapshot_pending",
                    completeness="full" if full else "partial",
                    full_jd_text_stored=full,
                    identity_unverified=False,
                )
            else:
                pending = JobIntakeService(repository.database).repository.get(
                    row["intake_id"], candidate
                )
                runtime = {
                    **public_state(pending),
                    "identity_unverified": pending.job_url is None,
                    "full_jd_text_stored": pending.snapshot_id is not None,
                }
            projected.append(
                json.dumps(
                    {**json.loads(row["source_line"]), "runtime": runtime}, ensure_ascii=False
                )
            )
        atomic_text(output, "\n".join(projected) + "\n")
        return {
            "rows": len(rows),
            "projection_digest": file_digest(output),
            "state_authority": "pipeline_jobs",
        }

    def rollback(
        self, database: Path, migration_id: str, *, candidate_id: str | None = None
    ) -> dict[str, object]:
        database = database.resolve()
        manifest = self.manifest(database, migration_id, candidate_id=candidate_id)
        backup = Path(str(manifest["backup_path"]))
        if (
            migration_database_digest(database) != manifest["post_database_digest"]
            or migration_database_digest(backup) != manifest["backup_digest"]
        ):
            reject("Later facts or changed backup prevent destructive migration rollback.")
        if any(Path(str(database) + suffix).exists() for suffix in ("-wal", "-journal")):
            reject("Stop all database writers before rollback.")
        descriptor, name = tempfile.mkstemp(
            dir=database.parent, prefix=".pipeline-rollback-", suffix=".sqlite3"
        )
        os.close(descriptor)
        temporary = Path(name)
        try:
            backup_database(backup, temporary)
            if migration_database_digest(database) != manifest["post_database_digest"]:
                reject("Database changed while rollback was prepared.")
            temporary.replace(database)
            return {
                "restored": True,
                "migration_id": migration_id,
                "source_digest": manifest["source_digest"],
            }
        finally:
            temporary.unlink(missing_ok=True)
