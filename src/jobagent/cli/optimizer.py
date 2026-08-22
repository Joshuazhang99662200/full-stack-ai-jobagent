"""Read-only discovery commands for Resume Optimizer capabilities."""

import json
from pathlib import Path
from typing import Annotated, Never

import typer

from jobagent.errors import CapabilityRegistryError
from jobagent.optimizer.index import CapabilityIndexLoader, CapabilityRegistryCompiler
from jobagent.schemas.optimizer_registry import CapabilityKind, CapabilityRegistrySnapshot

INDEX_PATHS = (
    Path("optimizer/index/repository.yaml"),
    Path("optimizer/index/policies.yaml"),
)


def _find_default_skill_root() -> Path:
    module_path = Path(__file__).resolve()
    for ancestor in module_path.parents:
        candidate = ancestor / "skills" / "job-hunting"
        if candidate.is_dir():
            return candidate
    return module_path.parents[3] / "skills" / "job-hunting"


DEFAULT_SKILL_ROOT = _find_default_skill_root()

optimizer_app = typer.Typer(
    help="Inspect Resume Optimizer capabilities.",
    no_args_is_help=True,
)


def _snapshot() -> CapabilityRegistrySnapshot:
    return CapabilityRegistryCompiler(
        CapabilityIndexLoader(DEFAULT_SKILL_ROOT)
    ).compile(INDEX_PATHS)


def _fail(error: CapabilityRegistryError) -> Never:
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
    raise typer.Exit(code=1)


@optimizer_app.command("capabilities")
def capabilities(
    kind: Annotated[
        CapabilityKind | None,
        typer.Option("--kind", help="Return only entries of this capability kind."),
    ] = None,
    intent: Annotated[
        str | None,
        typer.Option("--intent", help="Return only entries declaring this exact intent."),
    ] = None,
) -> None:
    """Inspect the checked-in capability index without loading indexed resources."""
    try:
        snapshot = _snapshot()
        if kind is None and intent is None:
            typer.echo(snapshot.model_dump_json(indent=2))
            return

        entries = tuple(
            entry
            for entry in snapshot.entries
            if (kind is None or entry.kind is kind)
            and (intent is None or intent in entry.intents)
        )
        typer.echo(
            json.dumps(
                {
                    "schema_version": snapshot.schema_version,
                    "source_digest": snapshot.digest,
                    "entries": [entry.model_dump(mode="json") for entry in entries],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    except CapabilityRegistryError as error:
        _fail(error)
