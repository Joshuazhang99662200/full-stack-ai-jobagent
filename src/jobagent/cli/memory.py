"""P1 offline memory inventory, immutable metadata snapshots and context selection."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from jobagent.bridge.memory_sources import PrivateSourceReader, private_path
from jobagent.cli.private_io import fail, open_database, read_model
from jobagent.errors import ContractValidationError, JobAgentError
from jobagent.memory.effect import memory_effect_report, reply_outcomes, sent_from_ledger
from jobagent.memory.service import MemoryService
from jobagent.memory.simulation import simulate as run_simulation
from jobagent.memory.usage import summarize_memory_usage
from jobagent.schemas.common import ContractModel
from jobagent.schemas.memory import MemoryConfig
from jobagent.storage.candidate_repository import SqliteCandidateRepository
from jobagent.storage.conversation_repository import SqliteConversationRepository
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


@memory_app.command("effect")
def effect(
    candidate: Annotated[str, typer.Option("--candidate")],
    window_days: Annotated[
        int, typer.Option("--window-days", min=1, help="Reply observation window; required.")
    ],
    min_sample: Annotated[
        int, typer.Option("--min-sample", min=1, help="Closed sends needed per arm; required.")
    ],
    database: Annotated[Path, typer.Option("--database")] = Path(".jobagent/jobagent.sqlite3"),
) -> None:
    """Compare reply rates of memory-shaped greetings with greetings made without memory.

    Only closed windows count; small samples report insufficient_sample. The result
    is observational and grants nothing.
    """
    try:
        db = open_database(database)
        store = SqliteOutreachRepository(db)
        owned = {
            e.id for e in SqliteCandidateRepository(db).list_evidence(candidate)
            if e.user_confirmed and e.confidence.value != "weak"
        }
        conversations = SqliteConversationRepository(db)
        threads = [
            (conversation, conversations.list_events(conversation.conversation_id))
            for conversation in conversations.list_conversations()
        ]
        now = datetime.now(UTC)
        window = timedelta(days=window_days)
        items = sent_from_ledger(
            candidate, batches=store.list_batches(), audits=store.list_audits(),
            owned_evidence_ids=owned,
        )
        report = memory_effect_report(
            candidate, reply_outcomes(items, threads, now=now, window=window),
            window=window, min_sample=min_sample, observed_at=now,
        )
        typer.echo(report.model_dump_json(indent=2))
    except JobAgentError as error:
        fail(error)


@memory_app.command("simulate")
def simulate(
    trials: Annotated[int, typer.Option("--trials", min=1)],
    sample_size: Annotated[int, typer.Option("--sample-size", min=1, help="Sends per arm.")],
    base_rate: Annotated[float, typer.Option("--base-rate", min=0, max=1)],
    lift: Annotated[float, typer.Option("--lift", min=-1, max=1)],
    min_sample: Annotated[int, typer.Option("--min-sample", min=1)],
    seed: Annotated[int, typer.Option("--seed")] = 0,
) -> None:
    """Synthetic check: how often `memory effect` would claim or detect a difference."""
    try:
        typer.echo(run_simulation(
            trials=trials, sample_size=sample_size, base_rate=base_rate, lift=lift,
            min_sample=min_sample, seed=seed,
        ).model_dump_json(indent=2))
    except JobAgentError as error:
        fail(error)
