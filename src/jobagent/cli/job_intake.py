"""Muse-facing human intake, recoverable hand-offs and strategy consumption."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from jobagent.cli.private_io import fail, open_database, read_model
from jobagent.errors import ContractValidationError, JobAgentError
from jobagent.jobs.jd_snapshot import canonical_digest
from jobagent.jobs.job_intake import next_actions, public_state
from jobagent.jobs.lexicon import parse_lexicon
from jobagent.schemas.common import ContractModel
from jobagent.schemas.job_intake import (
    IntakeBatch,
    IntakeClaim,
    IntakeCommand,
    IntakeControl,
    IntakeDraft,
    IntakeInterest,
    IntakeRecord,
    IntakeRequest,
    IntakeResolve,
    IntakeReview,
    IntakeSearchRecord,
    IntakeSelection,
    IntakeSnapshot,
    IntakeStrategyInput,
)
from jobagent.schemas.lexicon import Lexicon
from jobagent.storage.candidate_repository import SqliteCandidateRepository
from jobagent.storage.intake_strategy import IntakeStrategyService
from jobagent.storage.job_intake_service import JobIntakeService

intake_app = typer.Typer(help="Persist human-selected jobs and resume host work; never sends.")
DatabaseOption = Annotated[Path, typer.Option("--database")]
CandidateOption = Annotated[str, typer.Option("--candidate")]
DEFAULT_DATABASE = Path(".jobagent/jobagent.sqlite3")


def echo(value: object) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2))


def parse_policy(path: Path) -> Lexicon:
    try:
        return parse_lexicon(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ContractValidationError("Private lexicon is unavailable.") from error


def register_mutation(name: str, contract: type[ContractModel], method: str) -> None:
    def command(path: Path, database: DatabaseOption = DEFAULT_DATABASE) -> None:
        try:
            request = read_model(path, contract)
            service = JobIntakeService(open_database(database))
            result = IntakeRecord.model_validate(
                getattr(service, method)(
                    request.model_dump(),
                    now=datetime.now(UTC),
                )
            )
            echo(public_state(result))
        except JobAgentError as error:
            fail(error)
        except ValidationError:
            fail(ContractValidationError("Private operation does not satisfy the intake contract."))

    intake_app.command(name)(command)


for command_name, model, operation in (
    ("resolve", IntakeResolve, "resolve"),
    ("snapshot", IntakeSnapshot, "attach_snapshot"),
    ("draft", IntakeDraft, "submit_draft"),
    ("review", IntakeReview, "review_draft"),
    ("batch", IntakeBatch, "attach_batch"),
    ("interest", IntakeInterest, "set_interest"),
    ("control", IntakeControl, "control"),
):
    register_mutation(command_name, model, operation)


@intake_app.command("enqueue")
def enqueue(path: Path, database: DatabaseOption = DEFAULT_DATABASE) -> None:
    try:
        service = JobIntakeService(open_database(database))
        result = service.enqueue(read_model(path, IntakeRequest), now=datetime.now(UTC))
        echo(public_state(result))
    except JobAgentError as error:
        fail(error)


@intake_app.command("factorize")
def factorization(
    path: Path,
    lexicon_path: Path,
    proposal_path: Annotated[Path | None, typer.Option("--model-output")] = None,
    database: DatabaseOption = DEFAULT_DATABASE,
) -> None:
    try:
        service = JobIntakeService(open_database(database))
        request = read_model(path, IntakeCommand)
        proposal = None
        if proposal_path is not None:
            try:
                proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                proposal = []
        result = service.factorize(
            request.model_dump(),
            parse_policy(lexicon_path),
            proposal=proposal,
            now=datetime.now(UTC),
        )
        echo(public_state(result))
    except JobAgentError as error:
        fail(error)


@intake_app.command("status")
def status(
    intake_id: str, candidate: CandidateOption, database: DatabaseOption = DEFAULT_DATABASE
) -> None:
    try:
        result = JobIntakeService(open_database(database)).synchronize(
            intake_id,
            candidate,
            now=datetime.now(UTC),
        )
        echo(public_state(result))
    except JobAgentError as error:
        fail(error)


@intake_app.command("list")
def list_records(
    candidate_id: str, domain: str, database: DatabaseOption = DEFAULT_DATABASE
) -> None:
    try:
        service = JobIntakeService(open_database(database))
        echo(
            [
                public_state(service.synchronize(r.intake_id, candidate_id, now=datetime.now(UTC)))
                for r in service.repository.list_records(candidate_id, domain)
            ]
        )
    except JobAgentError as error:
        fail(error)


@intake_app.command("history")
def history(
    intake_id: str, candidate: CandidateOption, database: DatabaseOption = DEFAULT_DATABASE
) -> None:
    try:
        service = JobIntakeService(open_database(database))
        echo(
            [
                {**e.model_dump(mode="json", exclude={"state"}), "state": public_state(e.state)}
                for e in service.repository.history(intake_id, candidate)
            ]
        )
    except JobAgentError as error:
        fail(error)


ACTION_CONTRACTS = {
    "resolve_target": "IntakeResolve",
    "fetch_full_jd": "IntakeSnapshot",
    "factorize": "IntakeCommand",
    "refresh_strategy": "IntakeStrategyInput",
    "generate_greeting": "IntakeDraft",
    "revise_greeting": "IntakeDraft",
    "independent_review": "IntakeReview",
    "prepare_outreach_batch": "IntakeBatch",
    "owner_resume": "IntakeControl",
}


@intake_app.command("next")
def next_work(
    intake_id: str, candidate: CandidateOption, database: DatabaseOption = DEFAULT_DATABASE
) -> None:
    try:
        service = JobIntakeService(open_database(database))
        row = service.synchronize(intake_id, candidate, now=datetime.now(UTC))
        actions = []
        for action in next_actions(row):
            action_id = "IA_" + canonical_digest([row.intake_id, row.version, action])[7:]
            base: dict[str, object] = {
                "event_id": action_id,
                "intake_id": row.intake_id,
                "candidate_id": row.candidate_id,
                "expected_version": row.version,
            }
            if action == "refresh_strategy":
                base = {
                    "candidate_id": row.candidate_id,
                    "domain": row.domain,
                    "source": row.platform,
                }
            elif action == "independent_review":
                base.update(draft_digest=row.draft_digest, snapshot_id=row.snapshot_id)
            elif action == "owner_resume":
                base.update(action="resume")
            actions.append(
                {
                    "action": action,
                    "action_id": action_id,
                    "contract": ACTION_CONTRACTS.get(action),
                    "input": base,
                    "policy_reference": "references/manual-job-intake.md",
                }
            )
        context: dict[str, object] = {
            "input_references": [
                {
                    "kind": r.entry_kind,
                    "message_reference": r.message_reference,
                    "target_reference": r.target_reference,
                    "list_version": r.list_version,
                }
                for r in row.requests
            ],
        }
        if row.job_id is not None:
            context["job"] = service.job(row).model_dump(mode="json")
        if row.snapshot_id is not None:
            context["snapshot"] = service.knowledge.get(row.snapshot_id).model_dump(mode="json")
            context["confirmed_evidence"] = [
                e.model_dump(mode="json")
                for e in SqliteCandidateRepository(service.database).list_evidence(candidate)
                if e.user_confirmed
            ]
            context["draft"] = row.draft.model_dump(mode="json") if row.draft else None
            context["review"] = row.review.model_dump(mode="json") if row.review else None
        echo(
            {
                "state": public_state(row),
                "actions": actions,
                "context": context,
                "grants_delivery_permission": False,
            }
        )
    except JobAgentError as error:
        fail(error)


@intake_app.command("strategy")
def strategy(path: Path, lexicon_path: Path, database: DatabaseOption = DEFAULT_DATABASE) -> None:
    try:
        request = read_model(path, IntakeStrategyInput)
        echo(
            IntakeStrategyService(open_database(database)).rebuild(
                request.model_dump(),
                parse_policy(lexicon_path),
                now=datetime.now(UTC),
            )
        )
    except JobAgentError as error:
        fail(error)


@intake_app.command("active")
def active(
    candidate_id: str, domain: str, source: str, database: DatabaseOption = DEFAULT_DATABASE
) -> None:
    try:
        echo(
            IntakeStrategyService(open_database(database)).active(
                candidate_id,
                domain,
                source,
                require_current=True,
            )
        )
    except JobAgentError as error:
        fail(error)


def register_strategy_operation(name: str, contract: type[ContractModel], method: str) -> None:
    def command(path: Path, database: DatabaseOption = DEFAULT_DATABASE) -> None:
        try:
            request = read_model(path, contract)
            service = IntakeStrategyService(open_database(database))
            echo(getattr(service, method)(request.model_dump(), now=datetime.now(UTC)))
        except JobAgentError as error:
            fail(error)

    intake_app.command(name)(command)


register_strategy_operation("claim", IntakeClaim, "claim")
register_strategy_operation("record-search", IntakeSearchRecord, "record_search")


@intake_app.command("selection")
def selection(path: Path, database: DatabaseOption = DEFAULT_DATABASE) -> None:
    try:
        request = read_model(path, IntakeSelection)
        echo(
            JobIntakeService(open_database(database)).save_selection(
                request.model_dump(),
                now=datetime.now(UTC),
            )
        )
    except JobAgentError as error:
        fail(error)
