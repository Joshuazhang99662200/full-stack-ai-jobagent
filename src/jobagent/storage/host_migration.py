"""Offline, backed-up queue adoption. Never promotes summaries or invents send proofs."""

import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime
from pathlib import Path

from pydantic import AwareDatetime, HttpUrl, TypeAdapter, ValidationError

from jobagent.errors import ContractValidationError
from jobagent.jobs.jd_snapshot import canonical_digest, text_digest
from jobagent.jobs.job_intake import public_state, reject
from jobagent.schemas.host_migration import (
    LegacyMappedRow,
    LegacyPartialSnapshot,
    LegacyTrackingBinding,
    QueueMigrationConfig,
)
from jobagent.schemas.job_intake import IntakeRequest
from jobagent.schemas.job_intelligence import JobListing
from jobagent.storage.database import Database
from jobagent.storage.job_intake_service import JobIntakeService
from jobagent.storage.sent_tracking_repository import SqliteSentTrackingRepository


def file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def database_digest(path: Path) -> str:
    """Include schema and facts; omit only the self-referential migration manifest rows."""
    hasher = hashlib.sha256()
    with Database(path).connect() as connection:
        hasher.update(str(connection.execute("PRAGMA user_version").fetchone()[0]).encode())
        schema = connection.execute(
            "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' "
            "ORDER BY type, name",
        ).fetchall()
        for row in schema:
            hasher.update(repr(tuple(row)).encode("utf-8"))
            if row["type"] != "table" or row["name"] == "host_migration_runs":
                continue
            name = row["name"].replace('"', '""')
            values = sorted(
                repr(tuple(value))
                for value in connection.execute(
                    f'SELECT * FROM "{name}"',
                ).fetchall()
            )
            for value in values:
                hasher.update(value.encode("utf-8"))
    return "sha256:" + hasher.hexdigest()


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=".host-", suffix=".tmp")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def backup_database(source: Path, target: Path) -> None:
    with closing(sqlite3.connect(source)) as connection, closing(sqlite3.connect(target)) as backup:
        connection.backup(backup)


class HostQueueMigrator:
    @staticmethod
    def raw_rows(source: Path) -> list[tuple[str, dict[str, object]]]:
        try:
            lines = source.read_text(encoding="utf-8-sig").splitlines()
            rows = []
            for line in lines:
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    reject("Legacy input must contain one JSON object per nonempty line.")
                rows.append((line, value))
            return rows
        except (OSError, ValueError) as error:
            raise ContractValidationError("Private queue could not be read as JSONL.") from error

    def inspect(self, source: Path) -> dict[str, object]:
        rows = self.raw_rows(source)
        fields: dict[str, set[str]] = {}
        for _, row in rows:
            for key, value in row.items():
                fields.setdefault(key, set()).add(type(value).__name__)
        return {
            "rows": len(rows),
            "source_digest": file_digest(source),
            "fields": {key: sorted(types) for key, types in sorted(fields.items())},
        }

    @staticmethod
    def scalar(row: dict[str, object], key: str, *, optional: bool = False) -> str | None:
        value = row.get(key)
        if value is None or value == "":
            if optional:
                return None
            reject("Required migration field is missing; supply an explicit field map.")
        if not isinstance(value, (str, int)) or isinstance(value, bool):
            reject("Migration identity fields must be literal strings or integers.")
        return str(value)

    def mapped(self, source: Path, config: QueueMigrationConfig) -> list[LegacyMappedRow]:
        rows = self.raw_rows(source)
        if len(rows) != config.expected_count:
            reject("Legacy row count differs from the explicit expected count.")
        values = []
        for ordinal, (line, raw) in enumerate(rows, start=1):
            fields = config.fields
            platform = self.scalar(raw, fields.platform) or ""
            try:
                values.append(
                    LegacyMappedRow(
                        row_id=self.scalar(raw, fields.row_id) or "",
                        platform=config.platform_values.get(platform, platform),
                        job_url=HttpUrl(self.scalar(raw, fields.job_url) or ""),
                        source_job_id=self.scalar(raw, fields.source_job_id, optional=True),
                        title=self.scalar(raw, fields.title, optional=True),
                        company=self.scalar(raw, fields.company, optional=True),
                        location=self.scalar(raw, fields.location, optional=True),
                        summary=self.scalar(raw, fields.summary, optional=True) or "",
                        legacy_status=self.scalar(raw, fields.status, optional=True),
                        observed_at=TypeAdapter(AwareDatetime | None).validate_python(
                            raw.get(fields.observed_at)
                        ),
                        source_line=line,
                        source_digest=text_digest(line),
                        source_json=raw,
                    )
                )
            except ValidationError as error:
                raise ContractValidationError(
                    "A legacy row does not match the explicit mapping.",
                    details={"ordinal": ordinal},
                ) from error
        ids = [row.row_id for row in values]
        if len(set(ids)) != len(ids) or not set(config.sent_row_ids) <= set(ids):
            reject("Legacy IDs must be unique and sent-row references must exist.")
        if len(set(config.sent_row_ids)) != len(config.sent_row_ids):
            reject("Sent-row references must not be duplicated.")
        return values

    @staticmethod
    def manifest(database: Path, migration_id: str) -> dict[str, object]:
        with Database(database).connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='host_migration_runs'",
            ).fetchone()
            row = (
                None
                if exists is None
                else connection.execute(
                    "SELECT manifest_json FROM host_migration_runs WHERE migration_id = ?",
                    (migration_id,),
                ).fetchone()
            )
        if row is None:
            reject("Migration manifest not found.")
        result: dict[str, object] = json.loads(row["manifest_json"])
        return result

    def sent_claims(
        self, source: Path | None, config: QueueMigrationConfig, row_ids: set[str]
    ) -> dict[str, dict[str, object]]:
        if source is None:
            if config.expected_sent_count:
                reject("The configured legacy send count requires its actual private sent file.")
            return {}
        rows = self.raw_rows(source)
        if config.expected_sent_count is not None and len(rows) != config.expected_sent_count:
            reject("Legacy sent-file row count differs from the explicit expected count.")
        result = {}
        for _, value in rows:
            row_id = self.scalar(value, config.sent_row_id_field) or ""
            if row_id not in row_ids or row_id in result:
                reject("Legacy sent rows must uniquely match existing queue IDs.")
            candidate = value.get("candidate_id")
            if candidate is not None and candidate != config.candidate_id:
                reject("Legacy sent evidence belongs to another candidate.")
            result[row_id] = value
        return result

    def migrate(
        self,
        source: Path,
        database: Path,
        config: QueueMigrationConfig,
        *,
        now: datetime,
        sent_source: Path | None = None,
    ) -> dict[str, object]:
        source, database = source.resolve(), database.resolve()
        if source == database or now.tzinfo is None:
            reject("Separate source and database paths and an aware clock are required.")
        rows = self.mapped(source, config)
        sent_source = sent_source.resolve() if sent_source else None
        claims = self.sent_claims(sent_source, config, {row.row_id for row in rows})
        sent_hash = file_digest(sent_source) if sent_source else None
        sent_ids = set(config.sent_row_ids) | set(claims)
        source_hash, config_hash = (
            file_digest(source),
            canonical_digest(config.model_dump(mode="json")),
        )
        if database.exists():
            with Database(database).connect() as connection:
                table = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='host_migration_runs'",
                ).fetchone()
                old = (
                    None
                    if table is None
                    else connection.execute(
                        "SELECT * FROM host_migration_runs WHERE migration_id = ?",
                        (config.migration_id,),
                    ).fetchone()
                )
            if old:
                if (
                    old["source_digest"] != source_hash
                    or old["config_digest"] != config_hash
                    or json.loads(old["manifest_json"]).get("sent_source_digest") != sent_hash
                ):
                    reject("A migration ID cannot change its source or field mapping.")
                result = self.verify(database, config.migration_id)
                return {**result, "replayed": True}
        if Path(str(database) + "-wal").exists() or Path(str(database) + "-journal").exists():
            reject("Stop all database writers and checkpoint pending journals before migration.")
        database.parent.mkdir(parents=True, exist_ok=True)
        backup_dir = database.parent / "migration-backups" / config.migration_id
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / "before.sqlite3"
        source_backup = backup_dir / "queue-original.jsonl"
        sent_backup = backup_dir / "sent-original.jsonl"
        original_digest = database_digest(database) if database.exists() else None
        descriptor, name = tempfile.mkstemp(
            dir=database.parent, prefix=".migration-", suffix=".sqlite3"
        )
        os.close(descriptor)
        temporary = Path(name)
        try:
            if database.exists():
                backup_database(database, temporary)
                if backup.exists() and database_digest(backup) != original_digest:
                    reject("Existing backup belongs to another baseline; use a new migration ID.")
                if not backup.exists():
                    backup_database(database, backup)
            else:
                Database(temporary).migrate()
                if not backup.exists():
                    backup_database(temporary, backup)
            if source_backup.exists() and file_digest(source_backup) != source_hash:
                reject("Existing source backup differs; use a new migration ID.")
            if not source_backup.exists():
                source_backup.write_bytes(source.read_bytes())
            if sent_source is not None:
                if sent_backup.exists() and file_digest(sent_backup) != sent_hash:
                    reject("Existing sent-file backup differs; use a new migration ID.")
                if not sent_backup.exists():
                    sent_backup.write_bytes(sent_source.read_bytes())
            Database(temporary).migrate()
            manifest: dict[str, object] = {
                "migration_id": config.migration_id,
                "candidate_id": config.candidate_id,
                "domain": config.domain,
                "row_ids": [row.row_id for row in rows],
                "source_rows": len(rows),
                "source_digest": source_hash,
                "config_digest": config_hash,
                "source_path": str(source),
                "source_backup_path": str(source_backup),
                "backup_path": str(backup),
                "backup_digest": database_digest(backup),
                "original_database_existed": original_digest is not None,
                "priority_ids": config.priority_ids,
                "imported_at": now.isoformat(),
                "send_reference_field": config.fields.send_reference,
                "sent_source_digest": sent_hash,
                "sent_source_path": str(sent_source) if sent_source else None,
                "sent_source_backup_path": str(sent_backup) if sent_source else None,
                "sent_send_reference_field": config.sent_send_reference_field,
            }
            service = JobIntakeService(Database(temporary))
            with service.database.connect() as connection, connection:
                connection.execute(
                    "INSERT INTO host_migration_runs VALUES (?, ?, ?, ?, ?)",
                    (
                        config.migration_id,
                        config.candidate_id,
                        source_hash,
                        config_hash,
                        json.dumps(manifest, ensure_ascii=False),
                    ),
                )
            intake_ids = []
            verified = 0
            for ordinal, row in enumerate(rows, start=1):
                key = canonical_digest([config.migration_id, row.row_id])[7:]
                record = service.enqueue(
                    IntakeRequest(
                        request_id="MIG_" + key,
                        candidate_id=config.candidate_id,
                        domain=config.domain,
                        platform=row.platform,
                        message_reference="LEGACY_" + key,
                        entry_kind="url",
                        target_reference=str(row.job_url),
                        job_url=row.job_url,
                        source_job_id=row.source_job_id,
                        intent="inspect",
                        occurred_at=now,
                    ),
                    now=now,
                )
                if row.observed_at is not None and row.source_job_id and row.title and row.company:
                    record = service.resolve(
                        {
                            "event_id": "RESOLVE_" + key,
                            "intake_id": record.intake_id,
                            "candidate_id": config.candidate_id,
                            "expected_version": record.version,
                            "listing": JobListing(
                                source=row.platform,
                                source_job_id=row.source_job_id,
                                title=row.title,
                                company=row.company,
                                location=row.location,
                                url=row.job_url,
                                collected_at=row.observed_at,
                            ).model_dump(),
                        },
                        now=now,
                    )
                    verified += 1
                partial = LegacyPartialSnapshot(
                    legacy_snapshot_id=canonical_digest(
                        [config.migration_id, row.row_id, row.source_digest]
                    ),
                    observed_at=row.observed_at,
                    imported_at=now,
                    summary=row.summary,
                )
                record = service.repository.update(
                    record.intake_id,
                    config.candidate_id,
                    event_id="PARTIAL_" + key,
                    expected_version=record.version,
                    kind="legacy_partial_registered",
                    changes={
                        "legacy_snapshot_id": partial.legacy_snapshot_id,
                        "blocked_reason": "legacy_partial",
                    },
                    now=now,
                )
                intake_ids.append(record.intake_id)
                with service.database.connect() as connection, connection:
                    connection.execute(
                        "INSERT INTO host_legacy_rows "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            config.migration_id,
                            ordinal,
                            row.row_id,
                            record.intake_id,
                            row.platform,
                            row.source_job_id,
                            str(row.job_url),
                            row.source_digest,
                            row.source_line,
                            json.dumps(row.source_json, ensure_ascii=False),
                            partial.model_dump_json(),
                            "proof_pending" if row.row_id in sent_ids else "not_declared_sent",
                            None,
                            json.dumps(claims[row.row_id], ensure_ascii=False)
                            if row.row_id in claims
                            else None,
                            canonical_digest(claims[row.row_id]) if row.row_id in claims else None,
                        ),
                    )
            if config.require_distinct_jobs and len(set(intake_ids)) != len(rows):
                reject(
                    "Canonical job count differs; review duplicates before explicit merged import."
                )
            manifest.update(
                canonical_intakes=len(set(intake_ids)),
                identity_verified=verified,
                proof_pending=len(sent_ids),
                replayed=False,
            )
            with service.database.connect() as connection, connection:
                connection.execute(
                    "UPDATE host_migration_runs SET manifest_json = ? WHERE migration_id = ?",
                    (json.dumps(manifest, ensure_ascii=False), config.migration_id),
                )
            manifest["post_database_digest"] = database_digest(temporary)
            with service.database.connect() as connection, connection:
                connection.execute(
                    "UPDATE host_migration_runs SET manifest_json = ? WHERE migration_id = ?",
                    (json.dumps(manifest, ensure_ascii=False), config.migration_id),
                )
            self.verify(temporary, config.migration_id)
            if sent_source is not None and file_digest(sent_source) != sent_hash:
                reject("Legacy sent file changed during migration.")
            if file_digest(source) != source_hash or (
                database.exists() and database_digest(database) != original_digest
            ):
                reject("Source or database changed during migration; no activation performed.")
            temporary.replace(database)
            return {**manifest, "valid": True}
        finally:
            temporary.unlink(missing_ok=True)

    def verify(self, database: Path, migration_id: str) -> dict[str, object]:
        manifest = self.manifest(database, migration_id)
        service = JobIntakeService(Database(database))
        with service.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM host_legacy_rows WHERE migration_id = ? ORDER BY ordinal",
                (migration_id,),
            ).fetchall()
        if [row["row_id"] for row in rows] != manifest["row_ids"]:
            reject("Migration row IDs or exact count no longer match the source manifest.")
        for row in rows:
            if row["sent_claim_json"] is not None and (
                canonical_digest(json.loads(row["sent_claim_json"])) != row["sent_claim_digest"]
            ):
                reject("Legacy sent-file evidence digest differs from the original.")
            record = service.repository.get(row["intake_id"], str(manifest["candidate_id"]))
            if (
                text_digest(row["source_line"]) != row["source_digest"]
                or json.loads(row["source_line"]) != json.loads(row["legacy_json"])
                or str(record.job_url) != row["job_url"]
                or record.platform != row["platform"]
                or (row["source_job_id"] and record.source_job_id != row["source_job_id"])
            ):
                reject("A legacy row hash or job identity differs from its original binding.")
        return {
            **manifest,
            "valid": True,
            "proof_pending": sum(row["tracking_proof_status"] == "proof_pending" for row in rows),
        }

    def project(self, database: Path, migration_id: str, output: Path) -> dict[str, object]:
        manifest = self.verify(database, migration_id)
        protected = {database.resolve()}
        for key in (
            "source_path",
            "source_backup_path",
            "backup_path",
            "sent_source_path",
            "sent_source_backup_path",
        ):
            if manifest.get(key):
                protected.add(Path(str(manifest[key])).resolve())
        if output.resolve() in protected:
            reject("Projection cannot overwrite original input, database or immutable backup.")
        service = JobIntakeService(Database(database))
        with service.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM host_legacy_rows WHERE migration_id = ? ORDER BY ordinal",
                (migration_id,),
            ).fetchall()
        projected = []
        for row in rows:
            record = service.repository.get(row["intake_id"], str(manifest["candidate_id"]))
            while record.merged_into:
                record = service.repository.get(record.merged_into, record.candidate_id)
            projected.append(
                json.dumps(
                    {
                        **json.loads(row["legacy_json"]),
                        "runtime": public_state(record),
                        "tracking_proof_status": row["tracking_proof_status"],
                    },
                    ensure_ascii=False,
                )
            )
        atomic_text(output, "\n".join(projected) + "\n")
        return {
            "rows": len(projected),
            "projection_digest": file_digest(output),
            "state_authority": "database",
        }

    def rollback(self, database: Path, migration_id: str) -> dict[str, object]:
        database = database.resolve()
        manifest = self.manifest(database, migration_id)
        backup = Path(str(manifest["backup_path"])).resolve()
        if (
            database_digest(database) != manifest["post_database_digest"]
            or database_digest(backup) != manifest["backup_digest"]
        ):
            reject(
                "Database changed after migration or backup differs; refusing destructive rollback."
            )
        if Path(str(database) + "-wal").exists() or Path(str(database) + "-journal").exists():
            reject("Stop all database writers before rollback.")
        descriptor, name = tempfile.mkstemp(
            dir=database.parent, prefix=".rollback-", suffix=".sqlite3"
        )
        os.close(descriptor)
        temporary = Path(name)
        try:
            backup_database(backup, temporary)
            if database_digest(database) != manifest["post_database_digest"]:
                reject("Database changed while rollback was being prepared.")
            temporary.replace(database)
            return {
                "restored": True,
                "migration_id": migration_id,
                "source_backup_path": manifest["source_backup_path"],
            }
        finally:
            temporary.unlink(missing_ok=True)

    def bind_tracking(self, database: Path, request: LegacyTrackingBinding) -> dict[str, object]:
        manifest = self.manifest(database, request.migration_id)
        if manifest["candidate_id"] != request.candidate_id:
            reject("Legacy mapping belongs to another candidate.")
        tracking = SqliteSentTrackingRepository(Database(database)).get(
            request.tracking_id,
            request.candidate_id,
        )
        with Database(database).connect() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM host_legacy_rows WHERE migration_id = ? AND row_id = ?",
                (request.migration_id, request.row_id),
            ).fetchone()
            if (
                row is None
                or row["platform"] != tracking.platform
                or row["job_url"] != str(tracking.job_url)
            ):
                reject("Verified tracking belongs to another legacy target.")
            original = json.loads(row["legacy_json"])
            original_send = original.get(str(manifest["send_reference_field"]))
            supplement = json.loads(row["sent_claim_json"]) if row["sent_claim_json"] else {}
            supplemental_send = supplement.get(
                str(manifest.get("sent_send_reference_field", "send_reference"))
            )
            if original_send and supplemental_send and original_send != supplemental_send:
                reject("Original queue and sent-file evidence disagree.")
            original_send = original_send or supplemental_send
            if not original_send or original_send not in tracking.send_references:
                reject(
                    "Legacy send needs its original send reference, approval and exact readback."
                )
            if row["tracking_id"] and row["tracking_id"] != request.tracking_id:
                reject("A legacy send cannot be rebound to a different tracked send.")
            connection.execute(
                "UPDATE host_legacy_rows SET tracking_proof_status = 'verified_tracking', "
                "tracking_id = ? "
                "WHERE migration_id = ? AND row_id = ?",
                (request.tracking_id, request.migration_id, request.row_id),
            )
        return {"bound": True, "row_id": request.row_id, "tracking_id": request.tracking_id}
