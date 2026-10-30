"""Explicit one-shot worker handoffs; no browser driver, approvals or scheduler."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, TypeVar

import typer
from pydantic import ValidationError

from jobagent.bridge.worker import WorkerGateway
from jobagent.errors import ContractValidationError, JobAgentError
from jobagent.schemas.common import ContractModel
from jobagent.schemas.worker import WorkerFetchRequest, WorkerReadback
from jobagent.sources import SourceRegistry
from jobagent.storage.database import Database

worker_app = typer.Typer(
    help="Typed local worker handoffs and single approved greetings.", no_args_is_help=True
)
DatabaseOption = Annotated[Path, typer.Option("--database", help="Explicit local database path.")]
SessionOption = Annotated[str, typer.Option("--session", help="Owner of the platform lease.")]
ModelT = TypeVar("ModelT", bound=ContractModel)


def _load(path: Path, contract: type[ModelT]) -> ModelT:
    try:
        return contract.model_validate_json(path.read_bytes())
    except (OSError, ValidationError) as error:
        raise ContractValidationError(
            "Worker input does not satisfy the required contract.",
            details={"contract": contract.__name__, "file_name": path.name},
        ) from error


def _gateway(path: Path, sources_dir: Path | None = None) -> WorkerGateway:
    path.parent.mkdir(parents=True, exist_ok=True)
    database = Database(path)
    database.migrate()
    return WorkerGateway(database, manifests=SourceRegistry.default(sources_dir).all())


def _run(action: Callable[[], ContractModel | list[ContractModel]]) -> None:
    try:
        result = action()
        if isinstance(result, ContractModel):
            typer.echo(result.model_dump_json(indent=2))
        else:
            typer.echo(
                json.dumps(
                    [i.model_dump(mode="json") for i in result], ensure_ascii=False, indent=2
                )
            )
    except JobAgentError as error:
        typer.echo(
            json.dumps(
                {"error": {"code": error.code, "message": error.message, "details": error.details}},
                ensure_ascii=False,
            )
        )
        raise typer.Exit(code=1) from error


@worker_app.command("ingest")
def ingest(
    request_path: Path,
    database: DatabaseOption,
    sources_dir: Annotated[Path | None, typer.Option("--sources-dir")] = None,
) -> None:
    """Validate observations and commit jobs plus their completion event atomically."""

    def action() -> ContractModel:
        request = _load(request_path, WorkerFetchRequest)
        return _gateway(database, sources_dir).ingest(request)

    _run(action)


@worker_app.command("claim-greeting")
def claim_greeting(
    batch_id: str,
    platform: Annotated[str, typer.Option("--platform")],
    session: SessionOption,
    database: DatabaseOption,
) -> None:
    """Reserve exactly one approved item under an existing platform lease."""
    _run(lambda: _gateway(database).claim_greeting(batch_id, platform, session))


@worker_app.command("authorize-greeting")
def authorize_greeting(task_id: str, session: SessionOption, database: DatabaseOption) -> None:
    """Recheck the live gate and issue one single-use dispatch authorization."""
    _run(lambda: _gateway(database).authorize_greeting(task_id, session))


@worker_app.command("record-greeting")
def record_greeting(readback_path: Path, database: DatabaseOption) -> None:
    """Check browser readback and commit one final audit plus its completion event."""

    def action() -> ContractModel:
        readback = _load(readback_path, WorkerReadback)
        return _gateway(database).record_greeting(readback)

    _run(action)


@worker_app.command("show")
def show(task_id: str, database: DatabaseOption) -> None:
    """Read one durable task result; never assume a parent agent status is proof."""

    def action() -> ContractModel:
        state = _gateway(database).show(task_id)
        if state is None:
            raise ContractValidationError("Worker task was not found.")
        return state

    _run(action)


@worker_app.command("events")
def events(database: DatabaseOption) -> None:
    """Read pending completion events once; this starts no listener or polling."""
    _run(lambda: list(_gateway(database).events()))


@worker_app.command("ack")
def acknowledge(event_id: str, database: DatabaseOption) -> None:
    """Acknowledge an existing completion event idempotently."""
    _run(lambda: _gateway(database).acknowledge(event_id))
