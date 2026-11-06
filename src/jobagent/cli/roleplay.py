"""Synthetic role-play evaluation of the memory loop; run from a fresh, empty directory.

The simulated owner reads `persona`, judges each `round`, and answers with
`decide`. The model behind `round` (the local Gemini CLI) never receives the
persona. Nothing here sends anything; the workspace is synthetic only.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from jobagent.bridge.gemini_runner import GeminiTextRunner
from jobagent.bridge.roleplay import (
    RoleplayPaths,
    build_report,
    decide_round,
    init_workspace,
    load_scenario,
    run_round,
)
from jobagent.cli.private_io import fail, read_model
from jobagent.errors import JobAgentError
from jobagent.schemas.roleplay import GeminiCliConfig, RoleplayDecision, RoleplayScenario

roleplay_app = typer.Typer(
    help="Synthetic role-play evaluation of preference memory; never sends.",
    no_args_is_help=True,
)


def _echo(value: object) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))


@roleplay_app.command("init")
def init(scenario: Annotated[str, typer.Option("--scenario")]) -> None:
    """Create the synthetic workspace under ./.jobagent/roleplay (must not exist)."""
    try:
        _echo(init_workspace(RoleplayPaths.here(), load_scenario(scenario), now=datetime.now(UTC)))
    except JobAgentError as error:
        fail(error)


@roleplay_app.command("persona")
def persona() -> None:
    """For the simulated owner only: the persona and its hidden preferences."""
    try:
        paths = RoleplayPaths.here()
        scenario = read_model(paths.scenario, RoleplayScenario)
        typer.echo(scenario.model_dump_json(
            indent=2, include={"display_name", "persona", "hidden_preferences", "evidence"}
        ))
    except JobAgentError as error:
        fail(error)


@roleplay_app.command("round")
def round_(
    gemini_config: Annotated[
        Path, typer.Option("--gemini-config", help="Private GeminiCliConfig JSON.")
    ],
) -> None:
    """Refresh memory, select rules and let the model draft and review the next greeting."""
    try:
        paths = RoleplayPaths.here()
        config = read_model(gemini_config, GeminiCliConfig)
        runner = GeminiTextRunner(config, paths.root / "runtime")
        typer.echo(run_round(paths, runner, now=datetime.now(UTC)).model_dump_json(indent=2))
    except JobAgentError as error:
        fail(error)


@roleplay_app.command("decide")
def decide(
    round_number: Annotated[int, typer.Argument(min=1)],
    decision_path: Annotated[Path, typer.Argument(help="RoleplayDecision JSON.")],
) -> None:
    """Record the simulated owner's decision through the real approval and feedback paths."""
    try:
        decision = read_model(decision_path, RoleplayDecision)
        _echo(decide_round(RoleplayPaths.here(), round_number, decision, now=datetime.now(UTC)))
    except JobAgentError as error:
        fail(error)


@roleplay_app.command("report")
def report() -> None:
    """Invariant checks, hidden-preference capture and the acceptance trend so far."""
    try:
        typer.echo(build_report(RoleplayPaths.here()).model_dump_json(indent=2))
    except JobAgentError as error:
        fail(error)
