"""Candidate-scoped, non-migrating snapshots of authoritative local data."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import TypeAdapter

from jobagent.console.activities import TERMINAL_PHASES, read_activities, validate_activities
from jobagent.console.assessments import attach_assessments
from jobagent.errors import JobAgentError
from jobagent.schemas.candidate import CandidateId
from jobagent.schemas.console import (
    ConsoleActivityInput,
    ConsoleJob,
    ConsoleRun,
    ConsoleSnapshot,
    ConsoleSource,
)
from jobagent.schemas.pipeline import PipelineHistory, PipelineJob, PipelineMeta
from jobagent.storage.database import LATEST_SCHEMA_VERSION
from jobagent.storage.harness_store import HarnessStore


def definitions() -> dict[str, Any]:
    return {
        "snapshot": ConsoleSnapshot.model_json_schema(),
        "activity": ConsoleActivityInput.model_json_schema(),
    }


def _jobs(database: Path, result: ConsoleSnapshot) -> None:
    if not database.exists():
        result.sources.append(
            ConsoleSource(
                name="pipeline",
                status="missing",
                message="Local database is missing; no file created.",
            )
        )
        return
    connection = None
    try:
        connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version < 22 or version > LATEST_SCHEMA_VERSION:
            raise ValueError("Unsupported pipeline schema")
        rows = connection.execute(
            "SELECT p.*, m.meta_json FROM pipeline_jobs p "
            "LEFT JOIN pipeline_meta m USING(pipeline_id) WHERE candidate_id=? "
            "ORDER BY entered_at,pipeline_id",
            (result.candidate_id,),
        ).fetchall()
        jobs = []
        for row in rows:
            payload = dict(row)
            meta = PipelineMeta.model_validate_json(payload.pop("meta_json"))
            job = PipelineJob.model_validate(payload)
            if meta.pipeline_id != job.pipeline_id:
                raise ValueError("Pipeline identity mismatch")
            history = [
                PipelineHistory.model_validate(dict(item))
                for item in connection.execute(
                    "SELECT * FROM pipeline_state_history WHERE pipeline_id=? ORDER BY rowid",
                    (job.pipeline_id,),
                )
            ]
            jobs.append(ConsoleJob(job=job, meta=meta, history=history))
        assessment_valid = True
        for item in jobs:
            assessment_valid = attach_assessments(connection, item) and assessment_valid
        result.sources.append(
            ConsoleSource(
                name="assessments",
                status="complete" if assessment_valid else "invalid",
                message="Last stored candidate/job assessments only; no fresh evaluation implied.",
            )
        )
        result.jobs = jobs
        result.sources.append(ConsoleSource(name="pipeline", status="complete"))
    except (OSError, ValueError, sqlite3.Error):
        result.sources.append(
            ConsoleSource(
                name="pipeline",
                status="invalid",
                message="Pipeline source unavailable or incompatible.",
            )
        )
    finally:
        if connection:
            connection.close()


def snapshot(
    database: Path,
    workspace: Path,
    candidate_id: str,
    *,
    now: datetime | None = None,
) -> ConsoleSnapshot:
    candidate = TypeAdapter(CandidateId).validate_python(candidate_id)
    now = now or datetime.now(UTC)
    result = ConsoleSnapshot(candidate_id=candidate, generated_at=now)
    _jobs(database, result)
    if not any(source.name == "assessments" for source in result.sources):
        result.sources.append(
            ConsoleSource(
                name="assessments",
                status="missing",
                message="Pipeline data unavailable; assessments unknown.",
            )
        )
    store = HarnessStore(workspace)
    harness_status: Literal["complete", "missing", "invalid"] = (
        "complete" if store.root.exists() else "missing"
    )
    activities_status: Literal["complete", "missing", "invalid"] = "missing"
    for directory in sorted(store.root.glob("RUN_*")):
        try:
            if (directory / "state.json").is_symlink():
                raise ValueError("Run state cannot link outside the workspace")
            run = store.read(directory.name)
            if run.candidate_id != candidate:
                continue
            try:
                events = read_activities(directory)
                validate_activities(events, run, now)
                if events and activities_status != "invalid":
                    activities_status = "complete"
            except (OSError, ValueError, JobAgentError):
                events = []
                activities_status = "invalid"
            freshness: Literal["current", "stale", "terminal", "unknown"] = "unknown"
            if run.phase in TERMINAL_PHASES:
                freshness = "terminal"
            elif events:
                latest = max(item.occurred_at for item in events)
                freshness = "stale" if now - latest > timedelta(minutes=5) else "current"
            result.runs.append(ConsoleRun(run=run, activities=events, freshness=freshness))
        except (OSError, ValueError, JobAgentError):
            harness_status = "invalid"
    result.sources.extend(
        [
            ConsoleSource(name="harness", status=harness_status),
            ConsoleSource(
                name="activities",
                status=activities_status,
                message="Host observations only; unrecorded phase timing stays unknown.",
            ),
            ConsoleSource(
                name="approvals",
                status="unsupported",
                message="Legacy outreach batches lack candidate ownership; not joined.",
            ),
        ]
    )
    return result
