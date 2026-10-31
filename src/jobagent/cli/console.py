"""Portable read-only console queries and explicit host activity ingestion."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import typer

from jobagent.console.activities import record_activity
from jobagent.console.projection import definitions as field_definitions
from jobagent.console.projection import snapshot
from jobagent.console.server import make_server
from jobagent.errors import JobAgentError
from jobagent.schemas.console import ConsoleActivityInput

console_app = typer.Typer(help="Read-only console and explicit host observations.")
DatabaseOption = Annotated[Path, typer.Option("--database")]
WorkspaceOption = Annotated[Path, typer.Option("--workspace")]


def _output(action: Callable[[], object]) -> None:
    try:
        typer.echo(json.dumps(action(), ensure_ascii=False, indent=2))
    except (JobAgentError, OSError, ValueError):
        typer.echo(
            json.dumps(
                {
                    "error": {
                        "code": "CONSOLE_INPUT_UNAVAILABLE",
                        "message": "Console input unavailable or invalid.",
                    }
                }
            )
        )
        raise typer.Exit(1) from None


@console_app.command("definitions")
def definitions() -> None:
    _output(field_definitions)


@console_app.command("list")
def list_records(
    candidate_id: str,
    database: DatabaseOption = Path(".jobagent/jobagent.sqlite3"),
    workspace: WorkspaceOption = Path("."),
) -> None:
    _output(lambda: snapshot(database, workspace, candidate_id).model_dump(mode="json"))


@console_app.command("event")
def event(path: Path, workspace: WorkspaceOption = Path(".")) -> None:
    _output(
        lambda: record_activity(
            workspace,
            ConsoleActivityInput.model_validate_json(path.read_bytes()),
        ).model_dump(mode="json")
    )


@console_app.command("serve")
def serve(
    candidate_id: str,
    database: DatabaseOption = Path(".jobagent/jobagent.sqlite3"),
    workspace: WorkspaceOption = Path("."),
    assets: Annotated[Path, typer.Option("--assets")] = Path("frontend/dist"),
    port: Annotated[int, typer.Option("--port", min=1, max=65535)] = 8765,
) -> None:
    try:
        server = make_server(database, workspace, candidate_id, assets, port=port)
    except (OSError, ValueError):
        typer.echo(
            json.dumps(
                {
                    "error": {
                        "code": "CONSOLE_SERVER_UNAVAILABLE",
                        "message": "Local console server unavailable.",
                    }
                }
            )
        )
        raise typer.Exit(1) from None
    typer.echo(json.dumps({"url": f"http://127.0.0.1:{port}", "read_only": True}))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
