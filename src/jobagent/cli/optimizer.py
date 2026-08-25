"""Read-only discovery commands for Resume Optimizer capabilities."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Never

import typer

from jobagent.errors import CapabilityRegistryError, ContractValidationError, JobAgentError
from jobagent.optimizer.index import CapabilityIndexLoader, CapabilityRegistryCompiler
from jobagent.schemas.optimizer_registry import CapabilityKind, CapabilityRegistrySnapshot
from jobagent.skill_resources import default_skill_root

INDEX_PATHS = (
    Path("optimizer/index/repository.yaml"),
    Path("optimizer/index/policies.yaml"),
)


def _default_skill_root() -> Path:
    return default_skill_root()


optimizer_app = typer.Typer(
    help="Inspect Resume Optimizer capabilities.",
    no_args_is_help=True,
)


def _compile_snapshot() -> CapabilityRegistrySnapshot:
    return CapabilityRegistryCompiler(
        CapabilityIndexLoader(_default_skill_root())
    ).compile(INDEX_PATHS)


_snapshot_provider: Callable[[], CapabilityRegistrySnapshot] = _compile_snapshot


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
    raise typer.Exit(code=1)


@optimizer_app.command("capabilities")
def capabilities(
    kind: Annotated[
        CapabilityKind | None,
        typer.Option(
            "--kind",
            help="Return only entries of this capability kind.",
            case_sensitive=False,
        ),
    ] = None,
    intent: Annotated[
        str | None,
        typer.Option("--intent", help="Return only entries declaring this exact intent."),
    ] = None,
) -> None:
    """Inspect the checked-in capability index without loading indexed resources."""
    try:
        if intent is not None:
            intent = intent.strip()
            if not intent:
                raise ContractValidationError(
                    "Capability intent filter is invalid.",
                    details={"field": "intent"},
                )
        snapshot = _snapshot_provider()
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
    except (CapabilityRegistryError, ContractValidationError) as error:
        _fail(error)
