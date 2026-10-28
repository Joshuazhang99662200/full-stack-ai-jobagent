"""Private JD knowledge commands; never searches or contacts a recruiter."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from jobagent.cli.private_io import fail, open_database, read_model
from jobagent.errors import ContractValidationError, JobAgentError
from jobagent.jobs.jd_factorization import factorize
from jobagent.jobs.lexicon import lexicon_digest, parse_lexicon
from jobagent.jobs.query_derivation import SearchQueryDeriver
from jobagent.jobs.search_learning import rebuild_lexicon
from jobagent.schemas.jd_snapshot import JDSnapshotInput
from jobagent.schemas.lexicon import CombinationInput, CombinationRequest, JDFeatureSet, Lexicon
from jobagent.schemas.search_learning import SearchLearningRequest
from jobagent.storage.jd_snapshot_repository import SqliteJDSnapshotRepository
from jobagent.storage.job_repository import SqliteJobRepository

DatabaseOption = Annotated[Path, typer.Option("--database")]


def snapshot(path: Path, database: DatabaseOption = Path(".jobagent/jobagent.sqlite3")) -> None:
    try:
        result = SqliteJDSnapshotRepository(open_database(database)).capture(
            read_model(path, JDSnapshotInput),
        )
        typer.echo(result.model_dump_json(indent=2))
    except JobAgentError as error:
        fail(error)


def snapshots(job_id: str, database: DatabaseOption = Path(".jobagent/jobagent.sqlite3")) -> None:

    try:
        store = SqliteJDSnapshotRepository(open_database(database))
        typer.echo(
            json.dumps(
                {
                    "snapshots": [s.model_dump(mode="json") for s in store.list_snapshots(job_id)],
                    "discoveries": [d.model_dump(mode="json") for d in store.discoveries(job_id)],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    except JobAgentError as error:
        fail(error)


def register_knowledge_commands(app: typer.Typer) -> None:
    app.command("snapshot")(snapshot)
    app.command("snapshots")(snapshots)
    app.command("factorize")(factorization)
    app.command("lexicon-update")(lexicon_update)
    app.command("lexicon-show")(lexicon_show)
    app.command("combinations")(combinations)
    app.command("combinations-report")(combinations_report)


SnapshotIds = Annotated[list[str] | None, typer.Option("--snapshot-id")]


def _lexicon(path: Path) -> Lexicon:
    try:
        return parse_lexicon(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ContractValidationError("Private lexicon file is unavailable.") from error


def _features(
    store: SqliteJDSnapshotRepository, snapshot_ids: list[str] | None
) -> list[JDFeatureSet]:
    if not snapshot_ids:
        raise ContractValidationError("Select the persisted snapshots for this domain.")
    features = store.feature_sets(snapshot_ids)
    if set(snapshot_ids) != {value.snapshot_id for value in features}:
        raise ContractValidationError("Some selected snapshots still need factorization.")
    return features


def factorization(
    snapshot_id: str,
    lexicon_path: Path,
    database: DatabaseOption = Path(".jobagent/jobagent.sqlite3"),
    model_output: Annotated[Path | None, typer.Option("--model-output")] = None,
) -> None:
    try:
        store = SqliteJDSnapshotRepository(open_database(database))
        policy = _lexicon(lexicon_path)
        proposal = None
        if model_output is not None:
            try:
                proposal = json.loads(model_output.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                proposal = []
        result = factorize(store.get(snapshot_id), policy, proposal)
        version = store.save_features(result, lexicon_digest(policy))
        typer.echo(
            json.dumps(
                {
                    "feature_set_id": version,
                    "feature_set": result.model_dump(mode="json"),
                    "lexicon_digest": lexicon_digest(policy),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    except JobAgentError as error:
        fail(error)


def lexicon_update(
    lexicon_path: Path,
    signals_path: Path,
    snapshot_id: SnapshotIds = None,
    database: DatabaseOption = Path(".jobagent/jobagent.sqlite3"),
) -> None:
    try:
        store = SqliteJDSnapshotRepository(open_database(database))
        policy = _lexicon(lexicon_path)
        learning = read_model(signals_path, SearchLearningRequest)
        result = rebuild_lexicon(policy, _features(store, snapshot_id), learning)
        store.save_lexicon(learning.candidate_id, policy)
        store.save_lexicon(learning.candidate_id, result.lexicon)
        typer.echo(result.model_dump_json(indent=2))
    except JobAgentError as error:
        fail(error)


def lexicon_show(
    candidate_id: str,
    version_digest: str,
    database: DatabaseOption = Path(".jobagent/jobagent.sqlite3"),
) -> None:
    try:
        result = SqliteJDSnapshotRepository(open_database(database)).get_lexicon(
            candidate_id,
            version_digest,
        )
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    except JobAgentError as error:
        fail(error)


def combinations(
    lexicon_path: Path,
    request_path: Path,
    snapshot_id: SnapshotIds = None,
    database: DatabaseOption = Path(".jobagent/jobagent.sqlite3"),
) -> None:
    try:
        db = open_database(database)
        store = SqliteJDSnapshotRepository(db)
        policy = _lexicon(lexicon_path)
        request_input = read_model(request_path, CombinationInput)
        request = CombinationRequest(
            **request_input.model_dump(exclude={"schema_version"}),
            now=datetime.now(UTC),
            feature_sets=_features(store, snapshot_id),
            history=SqliteJobRepository(db).searches(),
        )
        result = SearchQueryDeriver().derive_combinations(policy, request)
        store.save_lexicon(request.candidate_id, policy)
        store.save_plan(policy, request, result)
        typer.echo(result.model_dump_json(indent=2))
    except JobAgentError as error:
        fail(error)


def combinations_report(
    plan_id: str,
    database: DatabaseOption = Path(".jobagent/jobagent.sqlite3"),
) -> None:
    try:
        result = SqliteJDSnapshotRepository(open_database(database)).get_plan(plan_id)
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    except JobAgentError as error:
        fail(error)
