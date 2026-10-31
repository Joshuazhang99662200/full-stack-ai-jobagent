"""Atomic private host observations; never approve or mutate business state."""

import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import TypeAdapter

from jobagent.errors import ContractValidationError
from jobagent.schemas.console import ConsoleActivity, ConsoleActivityInput
from jobagent.schemas.harness import HarnessRun
from jobagent.storage.harness_store import HarnessStore

TERMINAL_PHASES = {"completed", "failed", "cancelled"}
ACTIVITY_FILE = "console-activities.json"


def read_activities(directory: Path) -> list[ConsoleActivity]:
    path = directory / ACTIVITY_FILE
    if not path.exists():
        return []
    if path.is_symlink() or path.resolve().parent != directory.resolve():
        raise ContractValidationError("Activity records must remain in their run directory.")
    return TypeAdapter(list[ConsoleActivity]).validate_json(path.read_bytes())


def validate_activities(events: list[ConsoleActivity], run: HarnessRun, now: datetime) -> None:
    seen: set[str] = set()
    latest: dict[str, ConsoleActivity] = {}
    for item in events:
        if item.run_id != run.run_id or item.candidate_id != run.candidate_id:
            raise ContractValidationError("Activity ownership mismatch.")
        if (
            run.created_at.tzinfo is None
            or item.occurred_at < run.created_at
            or item.occurred_at > item.recorded_at
            or item.recorded_at > now
        ):
            raise ContractValidationError("Activity timestamps are invalid.")
        if item.event_id in seen:
            raise ContractValidationError("Activity event identity is duplicated.")
        seen.add(item.event_id)
        previous = latest.get(item.activity_id)
        if previous is None:
            if item.status != "started":
                raise ContractValidationError("Activity history has no recorded start.")
        elif (
            previous.activity != item.activity
            or previous.owner != item.owner
            or previous.job_id != item.job_id
            or item.occurred_at < previous.occurred_at
            or previous.status in {"completed", "failed"}
            or item.status == "started"
        ):
            raise ContractValidationError("Activity history has an invalid lifecycle.")
        latest[item.activity_id] = item


def record_activity(
    workspace: Path,
    request: ConsoleActivityInput,
    *,
    now: datetime | None = None,
) -> ConsoleActivity:
    now = now or datetime.now(UTC)
    if now.tzinfo is None or request.occurred_at > now:
        raise ContractValidationError("Activity observation cannot be future-dated.")
    store = HarnessStore(workspace)
    with store.lock(request.run_id):
        run = store.read(request.run_id)
        if run.candidate_id != request.candidate_id:
            raise ContractValidationError("Activity belongs to another candidate.")
        directory = store.directory(request.run_id)
        events = read_activities(directory)
        validate_activities(events, run, now)
        for previous in events:
            if previous.event_id == request.event_id:
                if previous.model_dump(exclude={"recorded_at"}) != request.model_dump():
                    raise ContractValidationError("An activity event cannot be changed.")
                return previous
        if run.phase in TERMINAL_PHASES:
            raise ContractValidationError("Terminal runs cannot acquire new activity observations.")
        lineage = [item for item in events if item.activity_id == request.activity_id]
        if lineage:
            previous = lineage[-1]
            if (
                previous.activity != request.activity
                or previous.owner != request.owner
                or previous.job_id != request.job_id
            ):
                raise ContractValidationError(
                    "Activity identity cannot change within its lifecycle."
                )
            if previous.status in {"completed", "failed"} or request.status == "started":
                raise ContractValidationError(
                    "Closed activities cannot restart; use a new identity."
                )
            if request.occurred_at < previous.occurred_at:
                raise ContractValidationError(
                    "Activity observations must preserve chronological order."
                )
        elif request.status != "started":
            raise ContractValidationError("An activity requires a recorded start.")
        if run.created_at.tzinfo is None or request.occurred_at < run.created_at:
            raise ContractValidationError("Activity cannot precede its run.")
        item = ConsoleActivity(**request.model_dump(), recorded_at=now)
        events.append(item)
        path = directory / ACTIVITY_FILE
        temporary = directory / f".{uuid4().hex}.tmp"
        try:
            temporary.write_bytes(TypeAdapter(list[ConsoleActivity]).dump_json(events, indent=2))
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return item
