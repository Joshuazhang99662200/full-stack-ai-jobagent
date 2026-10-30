"""Reviewable dynamic-variable governance; no scheduling or external actions."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Never

import typer
from pydantic import ValidationError

from jobagent.bridge.dynamic_rules import load_rule_snapshot
from jobagent.errors import ContractValidationError, JobAgentError
from jobagent.rules.evaluation import (
    evaluate_abandonment,
    evaluate_backlog,
    evaluate_poll,
    evaluate_ratio,
)
from jobagent.rules.registry import definitions
from jobagent.rules.service import make_proposal
from jobagent.schemas.common import ContractModel
from jobagent.schemas.dynamic_rules import RuleChangeRequest, RuleConfirmation
from jobagent.schemas.rule_evaluation import AbandonmentObservation, RatioObservation
from jobagent.storage.database import Database
from jobagent.storage.rule_repository import SqliteRuleRepository

rules_app = typer.Typer(help="Explicit, versioned owner workflow parameters.", no_args_is_help=True)
DatabaseOption = Annotated[Path, typer.Option("--database")]
DEFAULT_DATABASE = Path(".jobagent/jobagent.sqlite3")


def _emit(value: object) -> None:
    if isinstance(value, ContractModel):
        value = value.model_dump(mode="json")
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2))


def _fail(error: Exception) -> Never:
    failure = (
        error
        if isinstance(error, JobAgentError)
        else ContractValidationError("Dynamic rule input or persistence failed.")
    )
    _emit({"error": {"code": failure.code, "message": failure.message, "details": failure.details}})
    raise typer.Exit(1)


def _private(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    parts = [part.casefold() for part in resolved.parts]
    if ".jobagent" not in parts and not any(
        parts[i : i + 2] == ["candidate", "private"] for i in range(len(parts) - 1)
    ):
        raise ContractValidationError("Rule settings and databases must remain private.")
    return resolved


def _repository(path: Path) -> SqliteRuleRepository:
    path = _private(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    database = Database(path)
    database.migrate()
    return SqliteRuleRepository(database)


@rules_app.command("definitions")
def show_definitions() -> None:
    """Show supported names, types and actual consumer bindings; no personal defaults."""
    _emit([item.model_dump(mode="json") for item in definitions()])


@rules_app.command("propose")
def propose(request_path: Path, database: DatabaseOption = DEFAULT_DATABASE) -> None:
    """Store the exact one-variable question. A proposal activates nothing."""
    try:
        request = RuleChangeRequest.model_validate_json(_private(request_path).read_bytes())
        repository = _repository(database)
        proposal = make_proposal(
            request, repository.current(request.candidate_id), now=datetime.now(UTC)
        )
        repository.save_proposal(proposal)
        _emit(proposal)
    except (JobAgentError, ValidationError, OSError, ValueError) as error:
        _fail(error)


@rules_app.command("approve")
def approve(
    proposal_id: str,
    candidate: Annotated[str, typer.Option("--candidate")],
    question_digest: Annotated[str, typer.Option("--question-digest")],
    answer: Annotated[str, typer.Option("--answer")],
    actor: Annotated[str, typer.Option("--actor")],
    database: DatabaseOption = DEFAULT_DATABASE,
) -> None:
    """Register an explicit owner response to a saved current question."""
    try:
        _emit(
            _repository(database).approve(
                RuleConfirmation(
                    proposal_id=proposal_id,
                    question_digest=question_digest,
                    answer=answer,
                    actor_id=actor,
                    confirmed_at=datetime.now(UTC),
                ),
                candidate_id=candidate,
            )
        )
    except (JobAgentError, ValidationError, OSError, ValueError) as error:
        _fail(error)


@rules_app.command("effective")
def effective(
    candidate_id: str,
    database: DatabaseOption = DEFAULT_DATABASE,
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Read current provenance and unannounced changes; reading is not notification."""
    try:
        repository = _repository(database)
        snapshot = repository.current(candidate_id)
        if snapshot is None:
            raise ContractValidationError("No confirmed dynamic rules exist for this candidate.")
        if output is not None:
            destination = _private(output)
            if destination.exists():
                raise ContractValidationError("Export to a new path to retain earlier snapshots.")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("x", encoding="utf-8") as stream:
                stream.write(snapshot.model_dump_json(indent=2))
        _emit(
            {
                "snapshot": snapshot.model_dump(mode="json"),
                "pending_changes": [
                    notice.model_dump(mode="json")
                    for notice in repository.pending_notices(candidate_id)
                ],
            }
        )
    except (JobAgentError, ValidationError, OSError, ValueError) as error:
        _fail(error)


@rules_app.command("history")
def history(candidate_id: str, database: DatabaseOption = DEFAULT_DATABASE) -> None:
    """Read immutable candidate rule versions; never recalculate old queue decisions."""
    try:
        _emit(
            [item.model_dump(mode="json") for item in _repository(database).history(candidate_id)]
        )
    except (JobAgentError, ValidationError, OSError, ValueError) as error:
        _fail(error)


@rules_app.command("acknowledge")
def acknowledge(
    candidate_id: str,
    version: str,
    reference: Annotated[str, typer.Option("--delivery-reference")],
    database: DatabaseOption = DEFAULT_DATABASE,
) -> None:
    """Record the host's actual change-notification reference, never a delivery approval."""
    try:
        _repository(database).acknowledge(
            candidate_id, version, reference=reference, at=datetime.now(UTC)
        )
        _emit({"candidate_id": candidate_id, "version": version, "acknowledged": True})
    except (JobAgentError, ValidationError, OSError, ValueError) as error:
        _fail(error)


@rules_app.command("evaluate")
def evaluate(
    kind: str,
    rules_file: Annotated[Path, typer.Option("--rules-file")],
    candidate: Annotated[str, typer.Option("--candidate")],
    observation: Annotated[Path | None, typer.Option("--observation")] = None,
    now: Annotated[str | None, typer.Option("--now")] = None,
    last_check_at: Annotated[str | None, typer.Option("--last-check-at")] = None,
    pending_review: Annotated[int | None, typer.Option("--pending-review", min=0)] = None,
) -> None:
    """Evaluate polling, abandonment, ratio or backlog without changing external state."""
    try:
        snapshot = load_rule_snapshot(rules_file, candidate)
        moment = datetime.fromisoformat(now) if now else datetime.now(UTC)
        if kind == "poll":
            _emit(
                evaluate_poll(
                    snapshot,
                    moment,
                    last_check_at=datetime.fromisoformat(last_check_at) if last_check_at else None,
                )
            )
        elif kind == "backlog" and pending_review is not None:
            _emit(evaluate_backlog(snapshot, pending_review))
        elif kind in {"abandonment", "ratio"} and observation is not None:
            body = _private(observation).read_bytes()
            if kind == "abandonment":
                _emit(
                    evaluate_abandonment(
                        snapshot,
                        AbandonmentObservation.model_validate_json(body),
                        moment,
                    )
                )
            else:
                _emit(evaluate_ratio(snapshot, RatioObservation.model_validate_json(body)))
        else:
            raise ContractValidationError("Unsupported evaluation or missing observation/count.")
    except (JobAgentError, ValidationError, OSError, ValueError) as error:
        _fail(error)
