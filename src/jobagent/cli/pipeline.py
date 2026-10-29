"""Private JSON adapters for the auditable pipeline; no browser, send or scheduling."""

import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from jobagent.cli.private_io import fail, open_database, read_model
from jobagent.errors import ContractValidationError, JobAgentError
from jobagent.schemas.common import ContractModel
from jobagent.schemas.pipeline import PipelineBindSend, PipelineCreate
from jobagent.schemas.pipeline_metrics import (
    PipelineMetricsComputeInput,
    PipelineStoredDiagnosisInput,
)
from jobagent.schemas.pipeline_migration import PipelineMigrationConfig
from jobagent.schemas.pipeline_recontact import PipelineBindReplyInput
from jobagent.schemas.pipeline_sync import PipelineSyncRequest
from jobagent.storage.pipeline_metrics import PipelineMetricsService
from jobagent.storage.pipeline_migration import PipelineMigrator
from jobagent.storage.pipeline_recontact import PipelineRecontactService
from jobagent.storage.pipeline_repository import Pair, PipelineRepository
from jobagent.storage.pipeline_service import PipelineService
from jobagent.storage.pipeline_sync import PipelineSyncService

pipeline_app = typer.Typer(
    help="Evidence-bound pipeline, private adoption and owner-reviewed improvement."
)
DatabaseOption = Annotated[Path, typer.Option("--database")]
CandidateOption = Annotated[str, typer.Option("--candidate")]
DEFAULT_DATABASE = Path(".jobagent/jobagent.sqlite3")


def json_default(value: object) -> object:
    if isinstance(value, ContractModel):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError("Unsupported private pipeline result.")


def output(operation: Callable[[], object]) -> None:
    try:
        typer.echo(json.dumps(operation(), ensure_ascii=False, indent=2, default=json_default))
    except JobAgentError as error:
        fail(error)
    except (OSError, UnicodeError, ValueError, TypeError, sqlite3.Error):
        fail(
            ContractValidationError(
                "Private pipeline input or storage artifact is unavailable or invalid."
            )
        )


def read_mapping(path: Path) -> dict[str, object]:
    try:
        value: dict[str, object] = json.loads(path.read_bytes())
    except (OSError, UnicodeError, ValueError) as error:
        raise ContractValidationError("Private pipeline JSON is unavailable or invalid.") from error
    if not isinstance(value, dict):
        raise ContractValidationError("Private pipeline input must be a JSON object.")
    return value


def pair_json(pair: Pair) -> dict[str, object]:
    job, meta = pair
    return {"job": job.model_dump(mode="json"), "meta": meta.model_dump(mode="json")}


@pipeline_app.command("create")
def create(path: Path, database: DatabaseOption = DEFAULT_DATABASE) -> None:
    output(
        lambda: pair_json(
            PipelineService(open_database(database)).create(
                read_model(path, PipelineCreate).model_dump(), now=datetime.now(UTC)
            )
        )
    )


@pipeline_app.command("transition")
def transition(path: Path, database: DatabaseOption = DEFAULT_DATABASE) -> None:
    # The service owns contract rejection auditing; do not discard invalid jumps here.
    output(
        lambda: pair_json(
            PipelineService(open_database(database)).transition(
                read_mapping(path), now=datetime.now(UTC)
            )
        )
    )


@pipeline_app.command("observe")
def observe(path: Path, database: DatabaseOption = DEFAULT_DATABASE) -> None:
    output(
        lambda: pair_json(
            PipelineService(open_database(database)).observe(
                read_mapping(path), now=datetime.now(UTC)
            )
        )
    )


@pipeline_app.command("bind-send")
def bind_send(path: Path, database: DatabaseOption = DEFAULT_DATABASE) -> None:
    output(
        lambda: pair_json(
            PipelineService(open_database(database)).bind_send(
                read_model(path, PipelineBindSend).model_dump(), now=datetime.now(UTC)
            )
        )
    )


@pipeline_app.command("bind-reply")
def bind_reply(path: Path, database: DatabaseOption = DEFAULT_DATABASE) -> None:
    output(
        lambda: pair_json(
            PipelineRecontactService(open_database(database)).bind_reply(
                read_model(path, PipelineBindReplyInput).model_dump(), now=datetime.now(UTC)
            )
        )
    )


@pipeline_app.command("sync")
def sync(path: Path, database: DatabaseOption = DEFAULT_DATABASE) -> None:
    output(
        lambda: pair_json(
            PipelineSyncService(open_database(database)).sync(
                read_model(path, PipelineSyncRequest).model_dump(), now=datetime.now(UTC)
            )
        )
    )


@pipeline_app.command("list")
def list_records(candidate_id: str, database: DatabaseOption = DEFAULT_DATABASE) -> None:
    output(
        lambda: [
            pair_json(pair)
            for pair in PipelineRepository(open_database(database)).list_records(candidate_id)
        ]
    )


@pipeline_app.command("form")
def form(candidate_id: str, database: DatabaseOption = DEFAULT_DATABASE) -> None:
    output(lambda: PipelineRepository(open_database(database)).form(candidate_id))


@pipeline_app.command("history")
def history(
    pipeline_id: str, candidate: CandidateOption, database: DatabaseOption = DEFAULT_DATABASE
) -> None:
    output(lambda: PipelineRepository(open_database(database)).history(pipeline_id, candidate))


@pipeline_app.command("due")
def due(candidate_id: str, database: DatabaseOption = DEFAULT_DATABASE) -> None:
    output(
        lambda: PipelineRepository(open_database(database)).due(candidate_id, now=datetime.now(UTC))
    )


@pipeline_app.command("inspect")
def inspect(source: Path) -> None:
    output(lambda: PipelineMigrator().inspect(source))


@pipeline_app.command("migrate")
def migrate(source: Path, config: Path, database: DatabaseOption = DEFAULT_DATABASE) -> None:
    # The offline migrator backs up the original before upgrading a temporary copy.
    output(
        lambda: PipelineMigrator().migrate(
            source, database, read_model(config, PipelineMigrationConfig), now=datetime.now(UTC)
        )
    )


@pipeline_app.command("verify-migration")
def verify_migration(
    migration_id: str, candidate: CandidateOption, database: DatabaseOption = DEFAULT_DATABASE
) -> None:
    output(lambda: PipelineMigrator().verify(database, migration_id, candidate_id=candidate))


@pipeline_app.command("project")
def project(
    migration_id: str,
    path: Path,
    candidate: CandidateOption,
    database: DatabaseOption = DEFAULT_DATABASE,
) -> None:
    output(lambda: PipelineMigrator().project(database, migration_id, path, candidate_id=candidate))


@pipeline_app.command("rollback")
def rollback(
    migration_id: str, candidate: CandidateOption, database: DatabaseOption = DEFAULT_DATABASE
) -> None:
    output(lambda: PipelineMigrator().rollback(database, migration_id, candidate_id=candidate))


@pipeline_app.command("metrics")
def metrics(path: Path, database: DatabaseOption = DEFAULT_DATABASE) -> None:
    output(
        lambda: PipelineMetricsService(open_database(database)).compute(
            read_model(path, PipelineMetricsComputeInput).model_dump(), now=datetime.now(UTC)
        )
    )


@pipeline_app.command("diagnose")
def diagnose(path: Path, database: DatabaseOption = DEFAULT_DATABASE) -> None:
    output(
        lambda: PipelineMetricsService(open_database(database)).diagnose(
            read_model(path, PipelineStoredDiagnosisInput).model_dump(), now=datetime.now(UTC)
        )
    )


@pipeline_app.command("metric-show")
def metric_show(
    metric_id: str, candidate: CandidateOption, database: DatabaseOption = DEFAULT_DATABASE
) -> None:
    def show() -> dict[str, object]:
        service = PipelineMetricsService(open_database(database))
        return {
            "metric": service.get_metric(metric_id, candidate).model_dump(mode="json"),
            "evidence": service.get_evidence(metric_id, candidate).model_dump(mode="json"),
        }

    output(show)


@pipeline_app.command("diagnosis-show")
def diagnosis_show(
    diagnosis_id: str, candidate: CandidateOption, database: DatabaseOption = DEFAULT_DATABASE
) -> None:
    output(
        lambda: PipelineMetricsService(open_database(database)).get_diagnosis(
            diagnosis_id, candidate
        )
    )


@pipeline_app.command("rule-propose")
def rule_propose(path: Path, database: DatabaseOption = DEFAULT_DATABASE) -> None:
    from jobagent.schemas.pipeline_rules import PipelineRuleProposalInput
    from jobagent.storage.pipeline_rules import PipelineRuleService

    output(
        lambda: PipelineRuleService(open_database(database)).propose(
            read_model(path, PipelineRuleProposalInput).model_dump(), now=datetime.now(UTC)
        )
    )


@pipeline_app.command("rule-confirm")
def rule_confirm(path: Path, database: DatabaseOption = DEFAULT_DATABASE) -> None:
    from jobagent.schemas.pipeline_rules import PipelineRuleConfirmationInput
    from jobagent.storage.pipeline_rules import PipelineRuleService

    output(
        lambda: PipelineRuleService(open_database(database)).confirm(
            read_model(path, PipelineRuleConfirmationInput).model_dump(), now=datetime.now(UTC)
        )
    )


@pipeline_app.command("confirmed-rules")
def confirmed_rules(candidate_id: str, database: DatabaseOption = DEFAULT_DATABASE) -> None:
    from jobagent.storage.pipeline_rules import PipelineRuleService

    output(lambda: PipelineRuleService(open_database(database)).confirmed(candidate_id))


@pipeline_app.command("rule-review")
def rule_review(path: Path, database: DatabaseOption = DEFAULT_DATABASE) -> None:
    from jobagent.schemas.pipeline_rules import PipelineRuleReviewInput
    from jobagent.storage.pipeline_rules import PipelineRuleService

    output(
        lambda: PipelineRuleService(open_database(database)).review(
            read_model(path, PipelineRuleReviewInput).model_dump(), now=datetime.now(UTC)
        )
    )


@pipeline_app.command("rule-show")
def rule_show(
    proposal_id: str, candidate: CandidateOption, database: DatabaseOption = DEFAULT_DATABASE
) -> None:
    from jobagent.storage.pipeline_rules import PipelineRuleService

    output(lambda: PipelineRuleService(open_database(database)).proposal(proposal_id, candidate))
