"""Private JD knowledge commands; never searches or contacts a recruiter."""

from pathlib import Path
from typing import Annotated

import typer

from jobagent.cli.private_io import fail, open_database, read_model
from jobagent.errors import JobAgentError
from jobagent.schemas.jd_snapshot import JDSnapshotInput
from jobagent.storage.jd_snapshot_repository import SqliteJDSnapshotRepository

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
    import json

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
