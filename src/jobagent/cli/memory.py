"""P1 offline memory inventory, immutable metadata snapshots and context selection."""

import sqlite3
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from jobagent.bridge.memory_sources import PrivateSourceReader, private_path
from jobagent.cli.private_io import fail, open_database, read_model
from jobagent.errors import ContractValidationError, JobAgentError
from jobagent.memory.service import MemoryService
from jobagent.memory.usage import summarize_memory_usage
from jobagent.schemas.common import ContractModel
from jobagent.schemas.memory import MemoryConfig
from jobagent.storage.memory_repository import MemoryRepository
from jobagent.storage.outreach_repository import SqliteOutreachRepository

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


@memory_app.command("usage")
def usage(
    candidate: Annotated[str, typer.Option("--candidate")],
    database: Annotated[Path, typer.Option("--database")] = Path(".jobagent/jobagent.sqlite3"),
) -> None:
    """Show which memory versions and preference rules reached drafted, approved and sent items.

    Read from the outreach ledger only; items without generation provenance are
    reported as unattributed. Grants no approval.
    """
    try:
        store = SqliteOutreachRepository(open_database(database))
        batches = store.list_batches()
        approvals = {
            batch.batch_id: approval
            for batch in batches
            if (approval := store.get_approval(batch.batch_id)) is not None
        }
        report = summarize_memory_usage(
            candidate, batches=batches, approvals=approvals, audits=store.list_audits(),
        )
        typer.echo(report.model_dump_json(indent=2))
    except JobAgentError as error:
        fail(error)
