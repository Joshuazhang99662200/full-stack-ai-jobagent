"""Online profile commands: keep what each board shows, and tell its versions apart.

The host reads the person's profile on a board in their own signed-in browser and
hands the sections over here. Reading only: nothing in this group writes to a
board. Each read is kept whole; a new version opens only when the words change.
"""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Never

import typer
from pydantic import TypeAdapter, ValidationError

from jobagent.errors import ContractValidationError, JobAgentError
from jobagent.evals.profile import next_profile_version, profile_digest
from jobagent.schemas.profile import ProfileField, ProfileSnapshot
from jobagent.storage.database import Database
from jobagent.storage.evals_repository import SqliteEvalsRepository

profile_app = typer.Typer(
    help="Online profile snapshots and versions (read only).", no_args_is_help=True
)

DatabaseOption = Annotated[Path, typer.Option("--database", help="Local SQLite path.")]
DEFAULT_DATABASE = Path(".jobagent/jobagent.sqlite3")


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


def _store(database: Path) -> SqliteEvalsRepository:
    database.parent.mkdir(parents=True, exist_ok=True)
    db = Database(database)
    db.migrate()
    return SqliteEvalsRepository(db)


@profile_app.command("snapshot")
def snapshot(
    fields_path: Annotated[
        Path, typer.Argument(help="JSON list of {name, text}: the profile sections as read.")
    ],
    platform: Annotated[str, typer.Option("--platform")],
    database: DatabaseOption = DEFAULT_DATABASE,
    now: Annotated[
        str | None, typer.Option("--now", help="ISO time it was read; defaults to now.")
    ] = None,
) -> None:
    """Keep one board's profile as read, and open a version if its words changed."""
    try:
        try:
            fields = TypeAdapter(list[ProfileField]).validate_json(fields_path.read_bytes())
        except (OSError, ValidationError):
            raise ContractValidationError(
                "The profile file must hold a JSON list of sections.",
                details={"file_name": fields_path.name},
            ) from None
        if not fields:
            raise ContractValidationError("A profile snapshot needs at least one section.")
        store = _store(database)
        try:
            current = ProfileSnapshot(
                snapshot_id=f"PROFSNAP_{uuid.uuid4().hex[:16].upper()}",
                platform=platform,
                captured_at=_now(now),
                fields=fields,
                digest=profile_digest(fields),
            )
        except ValidationError:
            raise ContractValidationError(
                "The profile sections are invalid (each name once)."
            ) from None
        versions = store.profile_versions(platform)
        latest = versions[-1] if versions else None
        latest_snapshot = (
            store.get_profile_snapshot(latest.snapshot_id) if latest is not None else None
        )
        store.save_profile_snapshot(current)
        version = next_profile_version(latest, latest_snapshot, current)
        if version is not None:
            store.save_profile_version(version)
        _emit(
            {
                "snapshot_id": current.snapshot_id,
                "digest": current.digest,
                "sections": [field.name for field in fields],
                "version": version.model_dump(mode="json") if version is not None else None,
            }
        )
    except (JobAgentError, ValueError) as error:
        _fail(error if isinstance(error, JobAgentError) else ContractValidationError(str(error)))


@profile_app.command("versions")
def versions(
    platform: Annotated[str, typer.Option("--platform")],
    database: DatabaseOption = DEFAULT_DATABASE,
) -> None:
    """List a board's profile versions, oldest first. Sections are named, not quoted."""
    try:
        _emit([v.model_dump(mode="json") for v in _store(database).profile_versions(platform)])
    except JobAgentError as error:
        _fail(error)
