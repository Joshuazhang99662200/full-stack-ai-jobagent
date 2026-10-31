"""Thin host-facing entry points for atomic read-only sourcing budgets."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Never, TypeVar

import typer
from pydantic import ValidationError

from jobagent.bridge.dynamic_rules import load_effective_rule_snapshot
from jobagent.errors import ContractValidationError, JobAgentError
from jobagent.rules.bindings import bind_read_cap, bind_sourcing_run
from jobagent.rules.rounds import apply_round_overrides
from jobagent.schemas.common import ContractModel
from jobagent.schemas.sources import HostBrowserSpec
from jobagent.schemas.sourcing import (
    SourcingAttemptRequest,
    SourcingQueryCapture,
    SourcingResultRequest,
    SourcingRunRequest,
)
from jobagent.sources import SourceRegistry
from jobagent.storage.database import Database
from jobagent.storage.query_repository import SqliteQueryRepository
from jobagent.storage.sourcing_repository import SqliteSourcingRepository

DatabaseOption = Annotated[Path, typer.Option("--database")]
ModelT = TypeVar("ModelT", bound=ContractModel)


def _fail(error: JobAgentError) -> Never:
    typer.echo(
        json.dumps(
            {
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "details": error.details,
                }
            },
            ensure_ascii=False,
        )
    )
    raise typer.Exit(1)


def _load(path: Path, model: type[ModelT]) -> ModelT:
    try:
        return model.model_validate_json(path.read_bytes())
    except (OSError, ValidationError) as error:
        raise ContractValidationError(
            "Sourcing input does not match the required contract.",
            details={"contract": model.__name__},
        ) from error


def _repository(path: Path) -> SqliteSourcingRepository:
    path.parent.mkdir(parents=True, exist_ok=True)
    database = Database(path)
    database.migrate()
    return SqliteSourcingRepository(database)


def _spec(source: str) -> HostBrowserSpec:
    manifest = next((item for item in SourceRegistry.default().all() if item.id == source), None)
    if manifest is None or manifest.host_browser is None:
        raise ContractValidationError("The source has no configured host-browser route.")
    return manifest.host_browser


def start(
    path: Path, database: DatabaseOption = Path(".jobagent/jobagent.sqlite3"),
    rules_file: Annotated[Path | None, typer.Option("--rules-file")] = None,
) -> None:
    """Freeze one board's round limits; this does not search."""
    try:
        if rules_file is not None:
            try:
                body = json.loads(path.read_bytes())
                if not isinstance(body, dict) or not isinstance(body.get("candidate_id"), str):
                    raise ValueError("Candidate scope required")
                rules = load_effective_rule_snapshot(rules_file, body["candidate_id"], database)
                assert rules is not None
                body.setdefault("rules_version", rules.version)
                request = SourcingRunRequest.model_validate(body)
            except (OSError, ValueError) as error:
                raise ContractValidationError(
                    "Sourcing request or candidate scope is invalid.",
                ) from error
            if request.round_overrides:
                base_version = rules.version
                rules = apply_round_overrides(
                    rules, request.round_overrides, run_id=request.run_id, now=datetime.now(UTC),
                )
                request = request.model_copy(update={
                    "rules_version": rules.version, "base_rules_version": base_version,
                })
            request = bind_sourcing_run(
                rules, request, source_ceiling=_spec(request.source).max_detail_reads_per_day,
            )
        else:
            request = _load(path, SourcingRunRequest)
            if request.rules_version is None:
                load_effective_rule_snapshot(None, request.candidate_id, database)
        default_cap = _spec(request.source).max_detail_reads_per_day
        cap = (
            request.daily_detail_cap
            if request.budget_profile == "muse-expanded-v1"
            else min(default_cap, request.daily_detail_cap or default_cap)
        )
        assert cap is not None
        result = _repository(database).start_run(request, now=datetime.now(UTC), daily_cap=cap)
        typer.echo(result.model_dump_json(indent=2))
    except JobAgentError as error:
        _fail(error)


def reserve(path: Path, database: DatabaseOption = Path(".jobagent/jobagent.sqlite3")) -> None:
    """Reserve before a query or detail read; only a fresh allowed result may execute."""
    try:
        request = _load(path, SourcingAttemptRequest)
        repo = _repository(database)
        run = repo.get_run(request.run_id)
        spec = _spec(run.source)
        if request.kind == "detail" and not any(
            str(request.url).startswith(prefix) for prefix in spec.detail_url_prefixes
        ):
            raise ContractValidationError("The detail URL is outside the configured board.")
        result = repo.reserve(request, now=datetime.now(UTC))
        typer.echo(result.model_dump_json(indent=2))
    except JobAgentError as error:
        _fail(error)


def complete(path: Path, database: DatabaseOption = Path(".jobagent/jobagent.sqlite3")) -> None:
    """Append the result; failed/cancelled reads never refund the reservation."""
    try:
        result = _repository(database).complete(
            _load(path, SourcingResultRequest),
            now=datetime.now(UTC),
        )
        typer.echo(result.model_dump_json(indent=2))
    except JobAgentError as error:
        _fail(error)


def take(path: Path, database: DatabaseOption = Path(".jobagent/jobagent.sqlite3")) -> None:
    """Take confirmed front rows from an actual accessible host query result."""
    try:
        repo = _repository(database)
        result = SqliteQueryRepository(repo.database).take(
            _load(path, SourcingQueryCapture), now=datetime.now(UTC),
        )
        typer.echo(result.model_dump_json(indent=2))
    except JobAgentError as error:
        _fail(error)


def budget(
    database: DatabaseOption = Path(".jobagent/jobagent.sqlite3"),
    budget_profile: Annotated[str, typer.Option("--budget-profile")] = "conservative",
    daily_detail_cap: Annotated[int | None, typer.Option("--daily-detail-cap")] = None,
    rules_file: Annotated[Path | None, typer.Option("--rules-file")] = None,
    candidate: Annotated[str | None, typer.Option("--candidate")] = None,
) -> None:
    """Meter attempts plus disclosed legacy observations, per source calendar day."""
    try:
        if (
            budget_profile not in {"conservative", "muse-expanded-v1"}
            or (daily_detail_cap is not None and not 1 <= daily_detail_cap <= 240)
            or (budget_profile == "muse-expanded-v1" and daily_detail_cap is None)
            or (budget_profile == "conservative" and (daily_detail_cap or 0) > 50)
        ):
            raise ContractValidationError(
                "Budget report needs a valid explicit policy and daily cap."
            )
        if rules_file is not None and candidate is None:
            raise ContractValidationError("Dynamic read budget requires an explicit candidate.")
        rules = load_effective_rule_snapshot(rules_file, candidate, database)
        if rules and (budget_profile != "conservative" or daily_detail_cap is not None):
            raise ContractValidationError(
                "Explicit profile/cap conflicts with dynamic read budget.",
            )
        repo = _repository(database)
        now = datetime.now(UTC)
        report = {
            item.id: repo.budget(
                item.id,
                daily_cap=(
                    bind_read_cap(rules, source_ceiling=item.host_browser.max_detail_reads_per_day)
                    if rules else daily_detail_cap
                    if budget_profile == "muse-expanded-v1"
                    else min(
                        item.host_browser.max_detail_reads_per_day,
                        daily_detail_cap or item.host_browser.max_detail_reads_per_day,
                    )
                )
                or 50,
                now=now,
            ).model_dump(mode="json")
            for item in SourceRegistry.default().all()
            if item.host_browser is not None
        }
        for row in report.values():
            row["attempts_today"] = row["read_today"] - row["legacy_unmetered"]
            row["legacy_estimate"] = row["legacy_unmetered"]
            row["profile"] = "standard" if rules else budget_profile
            if rules:
                row["rules_version"] = rules.version
        typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
    except JobAgentError as error:
        _fail(error)


def register_sourcing_commands(app: typer.Typer) -> None:
    app.command("sourcing-start")(start)
    app.command("sourcing-reserve")(reserve)
    app.command("sourcing-result")(complete)
    app.command("sourcing-budget")(budget)
    app.command("sourcing-take")(take)
