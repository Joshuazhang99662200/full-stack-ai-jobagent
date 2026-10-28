"""Offline host adoption and acceptance commands; no browser, messages or scheduling."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from jobagent.cli.private_io import fail, open_database, read_model
from jobagent.errors import ContractValidationError, JobAgentError
from jobagent.schemas.host_checks import HostPageObservation, HostRoundInput, HostTwoRoundInput
from jobagent.schemas.host_migration import (
    LegacyBackfillBinding,
    LegacyTrackingBinding,
    QueueMigrationConfig,
)
from jobagent.schemas.message_diff import (
    MessageDiffInput,
    MessageRuleConfirmation,
    MessageRuleProposal,
)
from jobagent.storage.host_backfill import HostBackfillService
from jobagent.storage.host_checks import HostPageService
from jobagent.storage.host_migration import HostQueueMigrator
from jobagent.storage.host_reports import HostRoundReporter
from jobagent.storage.message_diff_repository import MessageDiffRepository

host_app = typer.Typer(help="Offline Muse adoption, page evidence and round reports.")
DatabaseOption = Annotated[Path, typer.Option("--database")]
CandidateOption = Annotated[str, typer.Option("--candidate")]
DEFAULT_DATABASE = Path(".jobagent/jobagent.sqlite3")


def output(operation: Callable[[], object]) -> None:
    try:
        typer.echo(json.dumps(operation(), ensure_ascii=False, indent=2))
    except JobAgentError as error:
        fail(error)
    except (OSError, UnicodeError, ValidationError):
        fail(ContractValidationError("Private host input or artifact is unavailable or invalid."))


@host_app.command("inspect-queue")
def inspect_queue(source: Path) -> None:
    output(lambda: HostQueueMigrator().inspect(source))


@host_app.command("migrate-queue")
def migrate_queue(
    source: Path,
    config: Path,
    database: DatabaseOption = DEFAULT_DATABASE,
    sent_file: Annotated[Path | None, typer.Option("--sent-file")] = None,
) -> None:
    output(
        lambda: HostQueueMigrator().migrate(
            source,
            database,
            read_model(config, QueueMigrationConfig),
            now=datetime.now(UTC),
            sent_source=sent_file,
        )
    )


@host_app.command("verify-migration")
def verify_migration(migration_id: str, database: DatabaseOption = DEFAULT_DATABASE) -> None:
    output(lambda: HostQueueMigrator().verify(database, migration_id))


@host_app.command("project-queue")
def project_queue(
    migration_id: str, path: Path, database: DatabaseOption = DEFAULT_DATABASE
) -> None:
    output(lambda: HostQueueMigrator().project(database, migration_id, path))


@host_app.command("rollback-migration")
def rollback_migration(migration_id: str, database: DatabaseOption = DEFAULT_DATABASE) -> None:
    output(lambda: HostQueueMigrator().rollback(database, migration_id))


@host_app.command("bind-tracking")
def bind_tracking(path: Path, database: DatabaseOption = DEFAULT_DATABASE) -> None:
    output(
        lambda: HostQueueMigrator().bind_tracking(
            database,
            read_model(path, LegacyTrackingBinding),
        )
    )


@host_app.command("page-observe")
def page_observe(path: Path, database: DatabaseOption = DEFAULT_DATABASE) -> None:
    output(
        lambda: HostPageService(open_database(database)).record(
            read_model(path, HostPageObservation).model_dump(),
            now=datetime.now(UTC),
        )
    )


@host_app.command("page-status")
def page_status(candidate_id: str, database: DatabaseOption = DEFAULT_DATABASE) -> None:
    output(lambda: HostPageService(open_database(database)).latest(candidate_id))


@host_app.command("round-report")
def round_report(path: Path, database: DatabaseOption = DEFAULT_DATABASE) -> None:
    output(
        lambda: HostRoundReporter(open_database(database)).record(
            read_model(path, HostRoundInput).model_dump(),
            now=datetime.now(UTC),
        )
    )


@host_app.command("round-show")
def round_show(
    report_id: str, candidate: CandidateOption, database: DatabaseOption = DEFAULT_DATABASE
) -> None:
    output(lambda: HostRoundReporter(open_database(database)).get(report_id, candidate))


@host_app.command("verify-rounds")
def verify_rounds(path: Path, database: DatabaseOption = DEFAULT_DATABASE) -> None:
    output(
        lambda: HostRoundReporter(open_database(database)).verify_two(
            read_model(path, HostTwoRoundInput).model_dump(),
        )
    )


@host_app.command("round-template")
def round_template(candidate_id: str, domain: str) -> None:
    output(
        lambda: {
            "report_id": "ROUND_REPLACE",
            "candidate_id": candidate_id,
            "domain": domain,
            "run_ids": ["REPLACE_WITH_ACTUAL_RUN"],
            "started_at": None,
            "completed_at": None,
            "search_observation_ids": [],
            "manual_observation_ids": [],
            "dedup_count": None,
            "filter_reasons": None,
            "metrics_evidence_reference": None,
            "unfinished": ["Fill actual private evidence; null values are unknown, not zero."],
            "evidence_mode": "unverified",
            "host_evidence_reference": None,
            "template_only": True,
        }
    )


@host_app.command("backfill-plan")
def backfill_plan(
    migration_id: str,
    candidate: CandidateOption,
    database: DatabaseOption = DEFAULT_DATABASE,
    priority: Annotated[str | None, typer.Option("--priority")] = None,
) -> None:
    output(
        lambda: HostBackfillService(open_database(database)).plan(
            migration_id, candidate, priority.split(",") if priority is not None else None
        )
    )


@host_app.command("backfill-attach")
def backfill_attach(path: Path, database: DatabaseOption = DEFAULT_DATABASE) -> None:
    output(
        lambda: HostBackfillService(open_database(database)).attach(
            read_model(path, LegacyBackfillBinding).model_dump(), now=datetime.now(UTC)
        )
    )


@host_app.command("message-diff")
def message_diff(path: Path, database: DatabaseOption = DEFAULT_DATABASE) -> None:
    output(
        lambda: MessageDiffRepository(open_database(database)).record(
            read_model(path, MessageDiffInput).model_dump(), now=datetime.now(UTC)
        )
    )


@host_app.command("diff-report")
def diff_report(candidate_id: str, database: DatabaseOption = DEFAULT_DATABASE) -> None:
    output(lambda: MessageDiffRepository(open_database(database)).report(candidate_id))


@host_app.command("rule-propose")
def rule_propose(path: Path, database: DatabaseOption = DEFAULT_DATABASE) -> None:
    output(
        lambda: MessageDiffRepository(open_database(database)).propose(
            read_model(path, MessageRuleProposal).model_dump(), now=datetime.now(UTC)
        )
    )


@host_app.command("rule-confirm")
def rule_confirm(path: Path, database: DatabaseOption = DEFAULT_DATABASE) -> None:
    output(
        lambda: MessageDiffRepository(open_database(database)).confirm(
            read_model(path, MessageRuleConfirmation).model_dump(), now=datetime.now(UTC)
        )
    )


@host_app.command("confirmed-rules")
def confirmed_rules(candidate_id: str, database: DatabaseOption = DEFAULT_DATABASE) -> None:
    output(lambda: MessageDiffRepository(open_database(database)).confirmed_rules(candidate_id))
