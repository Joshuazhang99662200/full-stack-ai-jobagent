"""Patrol pacing commands: is a check due, and record that one started.

The host's scheduler may wake as often as it likes; it asks `patrol next` and
only patrols when the answer is due. The patrol itself is the host's work in the
person's own browser, following references/patrol.md.
"""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Never

import typer
from pydantic import TypeAdapter, ValidationError

from jobagent.errors import ContractValidationError, JobAgentError
from jobagent.patrol.schedule import decide
from jobagent.patrol.snapshot import diff_snapshots
from jobagent.schemas.patrol import (
    PatrolCheck,
    PatrolDecision,
    PatrolSchedule,
    PatrolSnapshot,
    SnapshotItem,
)
from jobagent.storage.conversation_repository import SqliteConversationRepository
from jobagent.storage.database import Database
from jobagent.storage.patrol_repository import SqlitePatrolRepository

patrol_app = typer.Typer(help="Patrol pacing: when to check the boards.", no_args_is_help=True)

DatabaseOption = Annotated[Path, typer.Option("--database", help="Local SQLite path.")]
DEFAULT_DATABASE = Path(".jobagent/jobagent.sqlite3")
NowOption = Annotated[
    str | None, typer.Option("--now", help="ISO time to judge at; defaults to now.")
]


def _emit(value: object) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _fail(error: JobAgentError) -> Never:
    typer.echo(
        json.dumps(
            {"error": {"code": error.code, "message": error.message, "details": error.details}},
            ensure_ascii=False,
        )
    )
    raise typer.Exit(1)


def _now(value: str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        raise ContractValidationError("--now needs a timezone offset.")
    return moment.astimezone(UTC)


def _stores(database: Path) -> tuple[SqlitePatrolRepository, SqliteConversationRepository]:
    database.parent.mkdir(parents=True, exist_ok=True)
    db = Database(database)
    db.migrate()
    return SqlitePatrolRepository(db), SqliteConversationRepository(db)


def _decide(
    moment: datetime,
    checks: SqlitePatrolRepository,
    conversations: SqliteConversationRepository,
) -> PatrolDecision:
    finished = checks.latest_finished()
    still_open = checks.latest_open()
    return decide(
        moment,
        PatrolSchedule(),
        last_check_at=finished.checked_at if finished else None,
        last_inbound_at=conversations.latest_recruiter_message_at(),
        open_check=(still_open.check_id, still_open.checked_at) if still_open else None,
    )


@patrol_app.command("next")
def next_check(database: DatabaseOption = DEFAULT_DATABASE, now: NowOption = None) -> None:
    """Say whether a patrol check is due now, at which rhythm, and when the next one is."""
    try:
        moment = _now(now)
        checks, conversations = _stores(database)
        decision = _decide(moment, checks, conversations)
        _emit(decision.model_dump(mode="json"))
    except (JobAgentError, ValueError) as error:
        _fail(error if isinstance(error, JobAgentError) else ContractValidationError(str(error)))


@patrol_app.command("record")
def record(database: DatabaseOption = DEFAULT_DATABASE, now: NowOption = None) -> None:
    """Record that a check starts now; refused when none is due."""
    try:
        moment = _now(now)
        checks, conversations = _stores(database)
        decision = _decide(moment, checks, conversations)
        if not decision.due:
            raise ContractValidationError(
                "No patrol check is due now.",
                details={"mode": decision.mode.value, "next_check_at": str(decision.next_check_at)},
            )
        check = PatrolCheck(
            check_id=f"PCHECK_{uuid.uuid4().hex[:16].upper()}",
            checked_at=moment,
            mode=decision.mode,
        )
        checks.record(check)
        _emit(check.model_dump(mode="json"))
    except (JobAgentError, ValueError) as error:
        _fail(error if isinstance(error, JobAgentError) else ContractValidationError(str(error)))


@patrol_app.command("finish")
def finish(
    check_id: str, database: DatabaseOption = DEFAULT_DATABASE, now: NowOption = None
) -> None:
    """Mark a check finished; the next one is paced from its start."""
    try:
        checks, _ = _stores(database)
        _emit(checks.finish(check_id, _now(now)).model_dump(mode="json"))
    except (JobAgentError, ValueError) as error:
        _fail(error if isinstance(error, JobAgentError) else ContractValidationError(str(error)))


@patrol_app.command("snapshot")
def snapshot(
    items_path: Annotated[Path, typer.Argument(help="JSON list of SnapshotItem the host read.")],
    platform: Annotated[str, typer.Option("--platform")],
    database: DatabaseOption = DEFAULT_DATABASE,
    check_id: Annotated[
        str | None, typer.Option("--check", help="The PCHECK_* it belongs to.")
    ] = None,
    now: NowOption = None,
) -> None:
    """Keep a board's message list and report what changed since the last one."""
    try:
        try:
            items = TypeAdapter(list[SnapshotItem]).validate_json(items_path.read_bytes())
        except (OSError, ValidationError):
            raise ContractValidationError(
                "The snapshot file must hold a JSON list of conversations.",
                details={"file_name": items_path.name},
            ) from None
        checks, _ = _stores(database)
        previous = next(iter(checks.snapshots(platform, limit=1)), None)
        current = PatrolSnapshot(
            snapshot_id=f"PSNAP_{uuid.uuid4().hex[:16].upper()}",
            platform=platform,
            captured_at=_now(now),
            check_id=check_id,
            items=items,
        )
        checks.save_snapshot(current)
        _emit(
            {
                "snapshot_id": current.snapshot_id,
                "items": len(items),
                "diff": diff_snapshots(previous, current).model_dump(mode="json"),
            }
        )
    except (JobAgentError, ValueError) as error:
        _fail(error if isinstance(error, JobAgentError) else ContractValidationError(str(error)))


@patrol_app.command("snapshots")
def snapshots(
    platform: Annotated[str, typer.Option("--platform")],
    database: DatabaseOption = DEFAULT_DATABASE,
    limit: Annotated[int, typer.Option("--limit")] = 20,
) -> None:
    """List kept snapshots of a board, newest first."""
    try:
        checks, _ = _stores(database)
        _emit(
            [
                {
                    "snapshot_id": kept.snapshot_id,
                    "captured_at": kept.captured_at.isoformat(),
                    "check_id": kept.check_id,
                    "items": len(kept.items),
                }
                for kept in checks.snapshots(platform, limit=limit)
            ]
        )
    except JobAgentError as error:
        _fail(error)
