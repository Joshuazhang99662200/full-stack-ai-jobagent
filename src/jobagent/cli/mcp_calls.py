"""Private adapters for actual read-only MCP execution and explicit observed facts."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Never, TypeVar

import typer
from pydantic import TypeAdapter, ValidationError

from jobagent.bridge.dynamic_rules import load_effective_rule_snapshot
from jobagent.connectors.mcp_gateway import McpReadGateway
from jobagent.connectors.mcp_stdio import StdioMcpRunner
from jobagent.errors import ContractValidationError, JobAgentError
from jobagent.schemas.common import ContractModel
from jobagent.schemas.mcp_calls import (
    McpCallReconciliation,
    McpCallRequest,
    McpDeliveryIntent,
    McpDeliveryObservation,
    McpRoundRequest,
)
from jobagent.schemas.mcp_transport import McpStdioConfig
from jobagent.storage.database import Database
from jobagent.storage.mcp_repository import SqliteMcpRepository
from jobagent.storage.pipeline_policy import current_rule_snapshot

mcp_app = typer.Typer(
    help="Versioned read-only MCP calls; no executable delivery.", no_args_is_help=True
)
DatabaseOption = Annotated[Path, typer.Option("--database")]
CandidateOption = Annotated[str, typer.Option("--candidate")]
RulesOption = Annotated[Path, typer.Option("--rules-file")]
DEFAULT_DATABASE = Path(".jobagent/jobagent.sqlite3")
ModelT = TypeVar("ModelT", bound=ContractModel)


def _private(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    parts = [part.casefold() for part in resolved.parts]
    if ".jobagent" not in parts and not any(
        parts[index : index + 2] == ["candidate", "private"] for index in range(len(parts) - 1)
    ):
        raise ContractValidationError("MCP inputs, transport and ledger must remain private.")
    return resolved


def _load(path: Path, contract: type[ModelT]) -> ModelT:
    return contract.model_validate_json(_private(path).read_bytes())


def _repository(path: Path, *, migrate: bool = False) -> SqliteMcpRepository:
    database = Database(_private(path))
    if not database.path.is_file():
        raise ContractValidationError("MCP requires an existing private configured workspace.")
    if migrate:
        database.migrate()
    return SqliteMcpRepository(database)


def _scope(repository: SqliteMcpRepository, run_id: str, candidate_id: str) -> None:
    if repository.get_round(run_id).candidate_id != candidate_id:
        raise ContractValidationError("MCP round belongs to another candidate.")


def _current(repository: SqliteMcpRepository, rules_file: Path, candidate_id: str) -> None:
    snapshot = load_effective_rule_snapshot(
        _private(rules_file),
        candidate_id,
        repository.database.path,
    )
    with repository.database.connect() as connection:
        current = current_rule_snapshot(connection, candidate_id)
    if snapshot is None or current is None or current.version != snapshot.version:
        raise ContractValidationError("MCP needs the authoritative current candidate snapshot.")


def _emit(value: object) -> None:
    if isinstance(value, ContractModel):
        value = value.model_dump(mode="json")
    elif isinstance(value, list):
        value = [
            item.model_dump(mode="json") if isinstance(item, ContractModel) else item
            for item in value
        ]
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2))


def _fail(error: Exception) -> Never:
    failure = (
        error
        if isinstance(error, JobAgentError)
        else ContractValidationError(
            "MCP private input or persistence is unavailable or invalid.",
        )
    )
    _emit({"error": {"code": failure.code, "message": failure.message, "details": failure.details}})
    raise typer.Exit(1)


@mcp_app.command("round-start")
def round_start(
    request_path: Path, rules_file: RulesOption, database: DatabaseOption = DEFAULT_DATABASE
) -> None:
    """Freeze confirmed limits; do not call a tool, charge usage or debit prior delivery."""
    try:
        request = _load(request_path, McpRoundRequest)
        repository = _repository(database, migrate=True)
        _current(repository, rules_file, request.candidate_id)
        _emit(repository.start_round(request, now=datetime.now(UTC)))
    except (JobAgentError, ValidationError, OSError, ValueError) as error:
        _fail(error)


@mcp_app.command("status")
def status(
    run_id: str, candidate: CandidateOption, database: DatabaseOption = DEFAULT_DATABASE
) -> None:
    """Read frozen versions and actual usage without invoking an upstream process."""
    try:
        repository = _repository(database)
        _scope(repository, run_id, candidate)
        _emit(repository.status(run_id))
    except (JobAgentError, ValidationError, OSError, ValueError) as error:
        _fail(error)


@mcp_app.command("round-close")
def round_close(
    run_id: str, candidate: CandidateOption, database: DatabaseOption = DEFAULT_DATABASE
) -> None:
    """Freeze resolved facts and actual delivered count for the next round's debit."""
    try:
        repository = _repository(database)
        _scope(repository, run_id, candidate)
        _emit(repository.close_round(run_id, now=datetime.now(UTC)))
    except (JobAgentError, ValidationError, OSError, ValueError) as error:
        _fail(error)


@mcp_app.command("batch")
def batch(
    request_path: Path,
    transport: Annotated[Path, typer.Option("--transport")],
    candidate: CandidateOption,
    rules_file: RulesOption,
    database: DatabaseOption = DEFAULT_DATABASE,
) -> None:
    """Execute one guarded read-only batch; any non-success keeps a nonzero exit code."""
    try:
        requests = TypeAdapter(list[McpCallRequest]).validate_json(
            _private(request_path).read_bytes(),
        )
        config = _load(transport, McpStdioConfig)
        repository = _repository(database)
        _current(repository, rules_file, candidate)
        if not requests:
            raise ContractValidationError("MCP batch requires explicit requests.")
        for request in requests:
            _scope(repository, request.run_id, candidate)
        run = repository.get_round(requests[0].run_id)
        runner = StdioMcpRunner(config, source=run.source)
        gateway = McpReadGateway(repository, runner, clock=lambda: datetime.now(UTC))
        receipts = gateway.execute_batch(requests)
        _emit(receipts)
        if any(receipt.status != "success" for receipt in receipts):
            raise typer.Exit(1)
    except (JobAgentError, ValidationError, OSError, ValueError) as error:
        _fail(error)


@mcp_app.command("reconcile")
def reconcile(
    request_path: Path, candidate: CandidateOption, database: DatabaseOption = DEFAULT_DATABASE
) -> None:
    """Record explicit readback of an unknown call; never rerun it or clear daily stops."""
    try:
        request = _load(request_path, McpCallReconciliation)
        repository = _repository(database)
        with repository.database.connect() as connection:
            original, _ = repository._call(connection, request.call_id)
        _scope(repository, original.run_id, candidate)
        _emit(repository.reconcile(request, now=datetime.now(UTC)))
    except (JobAgentError, ValidationError, OSError, ValueError) as error:
        _fail(error)


@mcp_app.command("delivery-prepare")
def delivery_prepare(
    request_path: Path, candidate: CandidateOption, database: DatabaseOption = DEFAULT_DATABASE
) -> None:
    """Check host handoff order only; grant no permission and execute no delivery."""
    try:
        request = _load(request_path, McpDeliveryIntent)
        repository = _repository(database)
        _scope(repository, request.run_id, candidate)
        _emit(repository.prepare_delivery(request, now=datetime.now(UTC)))
    except (JobAgentError, ValidationError, OSError, ValueError) as error:
        _fail(error)


@mcp_app.command("delivery-record")
def delivery_record(
    request_path: Path, candidate: CandidateOption, database: DatabaseOption = DEFAULT_DATABASE
) -> None:
    """Append an explicitly host-observed external fact with its actual provenance."""
    try:
        request = _load(request_path, McpDeliveryObservation)
        repository = _repository(database)
        _scope(repository, request.run_id, candidate)
        _emit(repository.record_delivery(request, now=datetime.now(UTC)))
    except (JobAgentError, ValidationError, OSError, ValueError) as error:
        _fail(error)


@mcp_app.command("delivery-reconcile")
def delivery_reconcile(
    request_path: Path, candidate: CandidateOption, database: DatabaseOption = DEFAULT_DATABASE
) -> None:
    """Resolve an existing unknown host observation; no send, retry or stop release."""
    try:
        request = _load(request_path, McpDeliveryObservation)
        repository = _repository(database)
        _scope(repository, request.run_id, candidate)
        _emit(repository.reconcile_delivery(request, now=datetime.now(UTC)))
    except (JobAgentError, ValidationError, OSError, ValueError) as error:
        _fail(error)
