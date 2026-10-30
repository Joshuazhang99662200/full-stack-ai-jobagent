"""Atomic authoritative pipeline state with immutable history, evidence and replay."""

import json
import re
import sqlite3
from collections.abc import Callable
from datetime import datetime

from pydantic import ValidationError

from jobagent.errors import ContractValidationError, StorageError
from jobagent.jobs.jd_snapshot import canonical_digest
from jobagent.jobs.job_intake import reject
from jobagent.jobs.pipeline import advance_pipeline, observe_pipeline, silence_deadline
from jobagent.schemas.pipeline import (
    PipelineArtifactBinding,
    PipelineHistory,
    PipelineJob,
    PipelineMeta,
    PipelineObservation,
    PipelineTransition,
    PipelineVerifiedEvidence,
)
from jobagent.storage.database import Database

Pair = tuple[PipelineJob, PipelineMeta]


class PipelineRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def current(self, connection: sqlite3.Connection, pipeline_id: str, candidate_id: str) -> Pair:
        row = connection.execute(
            "SELECT * FROM pipeline_jobs WHERE pipeline_id = ? AND candidate_id = ?",
            (pipeline_id, candidate_id),
        ).fetchone()
        saved = connection.execute(
            "SELECT meta_json FROM pipeline_meta WHERE pipeline_id = ?", (pipeline_id,)
        ).fetchone()
        if row is None or saved is None:
            reject("Pipeline not found for this candidate.")
        return PipelineJob.model_validate(dict(row)), PipelineMeta.model_validate_json(saved[0])

    def get(self, pipeline_id: str, candidate_id: str) -> Pair:
        with self.database.connect() as connection:
            return self.current(connection, pipeline_id, candidate_id)

    def list_records(self, candidate_id: str) -> list[Pair]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT pipeline_id FROM pipeline_jobs WHERE candidate_id = ? "
                "ORDER BY entered_at, pipeline_id",
                (candidate_id,),
            ).fetchall()
            return [self.current(connection, r[0], candidate_id) for r in rows]

    def form(self, candidate_id: str) -> list[dict[str, object]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM pipeline_job_form WHERE candidate_id = ? "
                "ORDER BY entered_at, pipeline_id",
                (candidate_id,),
            ).fetchall()
        return [
            PipelineJob.model_validate(dict(r)).model_dump(mode="json", exclude={"schema_version"})
            for r in rows
        ]

    def history(self, pipeline_id: str, candidate_id: str) -> list[PipelineHistory]:
        self.get(pipeline_id, candidate_id)
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM pipeline_state_history WHERE pipeline_id = ? ORDER BY rowid",
                (pipeline_id,),
            ).fetchall()
        return [PipelineHistory.model_validate(dict(r)) for r in rows]

    @staticmethod
    def write_job(
        connection: sqlite3.Connection,
        job: PipelineJob,
        meta: PipelineMeta,
        *,
        create: bool = False,
    ) -> None:
        values = job.model_dump(mode="json", exclude={"schema_version"})
        if create:
            fields = ", ".join(values)
            placeholders = ", ".join("?" for _ in values)
            connection.execute(
                f"INSERT INTO pipeline_jobs ({fields}) VALUES ({placeholders})",
                tuple(values.values()),
            )
            connection.execute(
                "INSERT INTO pipeline_meta VALUES (?, ?)", (job.pipeline_id, meta.model_dump_json())
            )
        else:
            fields = ", ".join(f"{field} = ?" for field in values if field != "pipeline_id")
            connection.execute(
                f"UPDATE pipeline_jobs SET {fields} WHERE pipeline_id = ?",
                (*[v for k, v in values.items() if k != "pipeline_id"], job.pipeline_id),
            )
            connection.execute(
                "UPDATE pipeline_meta SET meta_json = ? WHERE pipeline_id = ?",
                (meta.model_dump_json(), job.pipeline_id),
            )

    @staticmethod
    def append_history(connection: sqlite3.Connection, history: PipelineHistory) -> None:
        values = history.model_dump(mode="json", exclude={"schema_version"})
        connection.execute(
            "INSERT INTO pipeline_state_history VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            tuple(values.values()),
        )

    @staticmethod
    def replay(
        connection: sqlite3.Connection, event_id: str, candidate_id: str, digest: str
    ) -> Pair | None:
        old = connection.execute(
            "SELECT * FROM pipeline_requests WHERE event_id = ?", (event_id,)
        ).fetchone()
        if old:
            if old["candidate_id"] != candidate_id or old["input_digest"] != digest:
                reject("Pipeline event ID cannot change its original input or candidate.")
            payload = json.loads(old["response_json"])
            return PipelineJob.model_validate(payload["job"]), PipelineMeta.model_validate(
                payload["meta"]
            )
        return None

    @staticmethod
    def remember(connection: sqlite3.Connection, event_id: str, digest: str, pair: Pair) -> None:
        job, meta = pair
        connection.execute(
            "INSERT INTO pipeline_requests VALUES (?, ?, ?, ?, ?)",
            (
                event_id,
                job.candidate_id,
                job.pipeline_id,
                digest,
                json.dumps(
                    {"job": job.model_dump(mode="json"), "meta": meta.model_dump(mode="json")},
                    ensure_ascii=False,
                ),
            ),
        )

    def rejection(self, data: dict[str, object], *, now: datetime, code: str) -> None:
        identity = canonical_digest(json.loads(json.dumps(data, default=str)))
        pipe = data.get("pipeline_id")
        candidate = data.get("candidate_id")
        pipe = (
            pipe
            if isinstance(pipe, str) and re.fullmatch(r"PIPE_[A-F0-9]{16}(?:_R[1-9][0-9]*)?", pipe)
            else None
        )
        candidate = (
            candidate
            if isinstance(candidate, str) and re.fullmatch(r"CAND_[A-Z0-9_]+", candidate)
            else None
        )
        with self.database.connect() as connection, connection:
            connection.execute(
                "INSERT OR IGNORE INTO pipeline_rejections VALUES (?, ?, ?, ?, ?)",
                (identity, pipe, candidate, now.isoformat(), code),
            )

    def reject_invalid(self, data: dict[str, object], *, now: datetime) -> None:
        try:
            PipelineTransition.model_validate(data)
        except ValidationError:
            self.rejection(data, now=now, code="invalid_contract")
            reject("Pipeline transition does not satisfy its contract.")
        reject("Expected an invalid transition contract.")

    def create(
        self,
        job: PipelineJob,
        meta: PipelineMeta,
        *,
        event_id: str,
        evidence_reference: str,
        input_digest: str | None = None,
    ) -> Pair:
        digest = input_digest or canonical_digest(
            [job.model_dump(mode="json"), meta.model_dump(mode="json"), evidence_reference]
        )
        try:
            with self.database.connect() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                old = self.replay(connection, event_id, job.candidate_id, digest)
                if old:
                    return old
                if job.pipeline_state != "draft_pending" or meta.proof_status != "not_sent":
                    reject("New contacts begin pending; historical claims need offline adoption.")
                if meta.pipeline_id != job.pipeline_id:
                    reject("Pipeline metadata belongs to another contact round.")
                self.write_job(connection, job, meta, create=True)
                connection.execute(
                    "INSERT OR IGNORE INTO pipeline_authorities VALUES (?, ?, ?)",
                    (job.candidate_id, job.updated_at.isoformat(), evidence_reference),
                )
                self.append_history(
                    connection,
                    PipelineHistory(
                        history_id="PH_" + canonical_digest(event_id)[7:31].upper(),
                        pipeline_id=job.pipeline_id,
                        from_state=None,
                        to_state="draft_pending",
                        changed_at=job.entered_at,
                        evidence_kind="owner_message",
                        evidence_reference=evidence_reference,
                        reason_code="normal",
                    ),
                )
                self.remember(connection, event_id, digest, (job, meta))
                return job, meta
        except sqlite3.IntegrityError as error:
            raise ContractValidationError(
                "An active row already exists or contact identity conflicts."
            ) from error

    def mutate(
        self,
        event: PipelineTransition | PipelineObservation | PipelineArtifactBinding,
        *,
        now: datetime,
        input_digest: str | None = None,
        operation: Callable[
            [PipelineJob, PipelineMeta], tuple[PipelineJob, PipelineMeta, PipelineHistory | None]
        ],
    ) -> Pair:
        data = event.model_dump(mode="json")
        digest = input_digest or canonical_digest(data)
        try:
            with self.database.connect() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                old = self.replay(connection, event.event_id, event.candidate_id, digest)
                if old:
                    return old
                job, meta = self.current(connection, event.pipeline_id, event.candidate_id)
                changed, metadata, history = operation(job, meta)
                self.write_job(connection, changed, metadata)
                if history:
                    self.append_history(connection, history)
                if isinstance(event, PipelineTransition) and event.to_state in {
                    "greeting_sent",
                    "resume_sent",
                }:
                    reference = event.send_reference or event.evidence_reference
                    connection.execute(
                        "INSERT INTO pipeline_used_sends VALUES (?, ?, ?)",
                        (reference, job.pipeline_id, event.event_id),
                    )
                if isinstance(event, PipelineArtifactBinding) and event.kind == "send_proof_bound":
                    if event.send_reference is None:
                        reject("Proof binding requires an actual send reference.")
                    connection.execute("INSERT INTO pipeline_used_sends VALUES (?, ?, ?)",
                                       (event.send_reference, job.pipeline_id, event.event_id))
                self.remember(connection, event.event_id, digest, (changed, metadata))
                at = (
                    event.changed_at if isinstance(event, PipelineTransition) else event.observed_at
                )
                kind = "transition" if isinstance(event, PipelineTransition) else event.kind
                connection.execute(
                    "INSERT INTO pipeline_observations VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        event.event_id,
                        job.pipeline_id,
                        at.isoformat(),
                        kind,
                        event.evidence_reference,
                        json.dumps(data, ensure_ascii=False),
                    ),
                )
                return changed, metadata
        except ContractValidationError:
            self.rejection(data, now=now, code="transition_rejected")
            raise
        except sqlite3.IntegrityError as error:
            self.rejection(data, now=now, code="evidence_conflict")
            raise ContractValidationError(
                "Send proof is already bound or evidence conflicts."
            ) from error
        except sqlite3.Error as error:
            raise StorageError("Pipeline state ledger is unavailable.") from error

    def transition(
        self, event: PipelineTransition, proof: PipelineVerifiedEvidence, *, now: datetime
    ) -> Pair:
        return self.mutate(
            event,
            now=now,
            operation=lambda job, meta: advance_pipeline(job, meta, event, proof, now=now),
        )

    def observe(
        self,
        event: PipelineObservation,
        *,
        now: datetime,
        proof: PipelineVerifiedEvidence | None = None,
    ) -> Pair:
        return self.mutate(
            event,
            now=now,
            operation=lambda job, meta: observe_pipeline(job, meta, event, now=now, proof=proof),
        )

    def due(self, candidate_id: str, *, now: datetime) -> list[dict[str, object]]:
        result = []
        for job, meta in self.list_records(candidate_id):
            deadline = silence_deadline(job, meta)
            if deadline is not None and (
                meta.last_checked_at is None or meta.last_checked_at < now
            ):
                result.append(
                    {
                        "pipeline_id": job.pipeline_id,
                        "platform": job.platform,
                        "pipeline_state": job.pipeline_state,
                        "version": meta.version,
                        "deadline_at": deadline.isoformat(),
                        "expiry_due": deadline <= now,
                    }
                )
        return result
