"""P1 offline memory inventory, immutable metadata snapshots and context selection."""

import sqlite3
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from jobagent.bridge.memory_sources import PrivateSourceReader, private_path
from jobagent.cli.private_io import fail, read_model
from jobagent.errors import ContractValidationError, JobAgentError
from jobagent.memory.service import MemoryService
from jobagent.schemas.common import ContractModel
from jobagent.schemas.memory import MemoryConfig
from jobagent.storage.memory_repository import MemoryRepository

memory_app = typer.Typer(help="Private source inventory and deterministic context; no model calls.")
ConfigOption = Annotated[Path, typer.Option("--config")]
StoreOption = Annotated[Path, typer.Option("--store")]


def _run(
    config: Path,
    store: Path,
    operation: str,
    *,
    snapshot: str = "",
    task: str = "",
    job: str | None = None,
) -> None:
    try:
        settings = read_model(private_path(config), MemoryConfig)
        service = MemoryService(
            settings, PrivateSourceReader(settings, store), MemoryRepository(store)
        )
        result: ContractModel
        if operation == "status":
            result = service.status()
        elif operation == "compile":
            result = service.compile()
        else:
            result = service.context(
                snapshot, task=task, job_id=job, candidate_id=settings.candidate_id
            )
        typer.echo(result.model_dump_json(indent=2))
    except JobAgentError as error:
        fail(error)
    except (OSError, sqlite3.Error, ValidationError, UnicodeError):
        fail(ContractValidationError("Private memory input or sidecar is unavailable or invalid."))


@memory_app.command("status")
def status(config: ConfigOption, store: StoreOption) -> None:
    _run(config, store, "status")


@memory_app.command("compile")
def compile_snapshot(config: ConfigOption, store: StoreOption) -> None:
    _run(config, store, "compile")


@memory_app.command("context")
def context(
    config: ConfigOption,
    store: StoreOption,
    snapshot: Annotated[str, typer.Option("--snapshot")],
    task: Annotated[str, typer.Option("--task")],
    job: Annotated[str | None, typer.Option("--job")] = None,
) -> None:
    _run(config, store, "context", snapshot=snapshot, task=task, job=job)
