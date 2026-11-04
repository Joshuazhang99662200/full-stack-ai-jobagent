"""Explicit public board reads; no sending, approvals or online profile changes."""

import json
import sqlite3
from pathlib import Path
from typing import Annotated, Never

import typer
from pydantic import ValidationError

from jobagent.bridge.dynamic_rules import load_effective_rule_snapshot
from jobagent.connectors.public_careers_service import PublicCareersService
from jobagent.errors import ContractValidationError, JobAgentError
from jobagent.jobs.public_careers import BUDGET_NAMES
from jobagent.schemas.public_careers import PublicCareerConfig
from jobagent.storage.database import Database
from jobagent.storage.public_careers_repository import SqlitePublicCareersRepository

public_careers_app = typer.Typer(help="Read-only fixed public ATS boards.", no_args_is_help=True)
DatabaseOption = Annotated[Path, typer.Option("--database")]
CandidateOption = Annotated[str, typer.Option("--candidate-id")]


def fail(error: Exception) -> Never:
    error = (
        error
        if isinstance(error, JobAgentError)
        else ContractValidationError("Cannot read valid public careers configuration or storage.")
    )
    typer.echo(
        json.dumps(
            {"error": {"code": error.code, "message": error.message, "details": error.details}},
            ensure_ascii=False,
        )
    )
    raise typer.Exit(1)


@public_careers_app.command("scan")
def scan(
    candidate_id: CandidateOption,
    config: Annotated[Path, typer.Option("--config")],
    rules_file: Annotated[Path, typer.Option("--rules-file")],
    run_id: Annotated[str, typer.Option("--run-id")],
    database: DatabaseOption = Path(".jobagent/jobagent.sqlite3"),
) -> None:
    """Query explicit public boards using current owner-confirmed limits."""
    try:
        settings = PublicCareerConfig.model_validate_json(config.read_bytes())
        rules = load_effective_rule_snapshot(rules_file, candidate_id, database)
        if rules is None:
            raise ContractValidationError("Public careers requires confirmed dynamic rules.")
        if not database.is_file():
            raise ContractValidationError("Existing confirmed-rules database is required.")
        missing = [name for name in BUDGET_NAMES if name not in rules.values]
        if missing:
            raise ContractValidationError(
                "Public careers confirmed budgets are not configured.", details={"missing": missing}
            )
        typer.echo(
            json.dumps(
                {
                    "event": "public_careers_preflight",
                    "schema_version": "1.0",
                    "candidate_id": candidate_id,
                    "rules_version": rules.version,
                    "budgets": {name: rules.values[name] for name in BUDGET_NAMES},
                    "sources": [board.source for board in settings.boards],
                    "filter_context": settings.filter_context.model_dump(mode="json"),
                    "grants_delivery_permission": False,
                },
                ensure_ascii=False,
            ),
            err=True,
        )
        store = Database(database)
        store.migrate()
        repository = SqlitePublicCareersRepository(store)
        run = PublicCareersService(repository).run(candidate_id, settings, rules, run_id)
        typer.echo(run.model_dump_json())
    except (JobAgentError, OSError, ValidationError, sqlite3.Error) as error:
        fail(error)


@public_careers_app.command("list")
def list_records(
    candidate_id: CandidateOption, database: DatabaseOption = Path(".jobagent/jobagent.sqlite3")
) -> None:
    """List candidate-scoped observations without creating or migrating storage."""
    try:
        records = SqlitePublicCareersRepository(Database(database)).list_records(candidate_id)
        typer.echo(
            json.dumps(
                {
                    "candidate_id": candidate_id,
                    "channel": "public_careers",
                    "records": [record.model_dump(mode="json") for record in records],
                },
                ensure_ascii=False,
            )
        )
    except (JobAgentError, OSError, ValidationError, sqlite3.Error) as error:
        fail(error)


@public_careers_app.command("status")
def status(
    candidate_id: CandidateOption, database: DatabaseOption = Path(".jobagent/jobagent.sqlite3")
) -> None:
    """Read coverage, request counts and recovery points without network access."""
    try:
        runs = SqlitePublicCareersRepository(Database(database)).list_runs(candidate_id)
        typer.echo(
            json.dumps(
                {
                    "candidate_id": candidate_id,
                    "channel": "public_careers",
                    "runs": [run.model_dump(mode="json") for run in runs],
                },
                ensure_ascii=False,
            )
        )
    except (JobAgentError, OSError, ValidationError, sqlite3.Error) as error:
        fail(error)
