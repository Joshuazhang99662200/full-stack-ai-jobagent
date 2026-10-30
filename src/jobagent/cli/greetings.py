"""Explicit private greeting generation; never asks, approves or sends."""

import json
import os
import shutil
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from jobagent.bridge.codex_runner import MODEL, CodexTextRunner
from jobagent.bridge.dynamic_rules import load_effective_rule_snapshot
from jobagent.bridge.greeting_context import load_greeting_request
from jobagent.bridge.greeting_generation import CodexGreetingProvider
from jobagent.bridge.preference_memory import refresh_preference_memory
from jobagent.bridge.preference_reasoning import CodexPreferenceProvider
from jobagent.errors import ContractValidationError, JobAgentError, UserInterventionRequiredError
from jobagent.outreach.generation import GreetingGenerator
from jobagent.outreach.preference_memory import PreferenceLearner
from jobagent.rules.bindings import greeting_guidance
from jobagent.schemas.greeting import GreetingRequest, GreetingSettings

greetings_app = typer.Typer(help="Generate and independently review whole greetings privately.")


def _private_path(path: Path) -> Path:
    resolved = path.resolve()
    workspace = Path.cwd().resolve()
    allowed = [
        root
        for root in [
            workspace.joinpath("candidate", "private").resolve(),
            workspace.joinpath(".jobagent").resolve(),
        ]
        if root.is_relative_to(workspace)
    ]
    if not any(resolved.is_relative_to(root) and resolved != root for root in allowed):
        raise ContractValidationError(
            "Greeting artifacts and settings must stay in a private path."
        )
    return resolved


def _find_executable(explicit: Path | None) -> str:
    if explicit is not None:
        path = explicit.resolve()
        if not path.is_file() or (os.name == "nt" and path.suffix.lower() != ".exe"):
            raise ContractValidationError("Choose an existing native Codex executable.")
        return str(path)
    found = shutil.which("codex.exe" if os.name == "nt" else "codex")
    if found is None:
        raise UserInterventionRequiredError(
            "No native Codex executable was found; use --codex-executable."
        )
    return found


def _load_settings(path: Path, candidate: str) -> GreetingSettings:
    config_path = _private_path(path)
    try:
        config = GreetingSettings.model_validate_json(config_path.read_bytes())
    except (OSError, ValidationError):
        raise ContractValidationError(
            "Greeting settings must contain a valid private policy."
        ) from None
    if config.candidate_id != candidate:
        raise ContractValidationError("Greeting settings belong to a different candidate.")
    return config


@greetings_app.command("generate")
def generate(
    candidate: Annotated[str, typer.Option("--candidate")],
    settings: Annotated[Path, typer.Option("--settings")],
    output: Annotated[Path, typer.Option("--output", help="New private output directory.")],
    database: Annotated[Path, typer.Option("--database")] = Path(".jobagent/jobagent.sqlite3"),
    job: Annotated[str | None, typer.Option("--job")] = None,
    feedback: Annotated[str | None, typer.Option("--feedback")] = None,
    codex_executable: Annotated[Path | None, typer.Option("--codex-executable")] = None,
    timeout: Annotated[float, typer.Option("--timeout")] = 120,
    rules_file: Annotated[Path | None, typer.Option("--rules-file")] = None,
) -> None:
    """Generate a default or stored-JD greeting and save it for human review."""
    try:
        destination = _private_path(output)
        config = _load_settings(settings, candidate)
        memory_path = _private_path(Path(config.memory_path)) if config.memory_path else None
        if destination.exists():
            raise ContractValidationError(
                "Use a new output directory to preserve earlier artifacts."
            )
        request = load_greeting_request(database, config, job_id=job, feedback=feedback)
        rules = load_effective_rule_snapshot(rules_file, candidate, database)
        if rules is not None:
            request = GreetingRequest.model_validate({
                **request.model_dump(), "guidance": [*request.guidance, *greeting_guidance(rules)],
                "dynamic_rules_version": rules.version,
            })
        executable = _find_executable(codex_executable)
        runtime = _private_path(Path.cwd() / ".jobagent" / "greeting-runtime")
        model = CodexTextRunner(executable, runtime, timeout_seconds=timeout)
        if memory_path is not None:
            preference_provider = CodexPreferenceProvider(model)
            memory = refresh_preference_memory(
                database, memory_path, candidate, preference_provider,
            )
            context = (
                request.job.jd_raw if request.job is not None else
                "Default greeting: infer common historical directions; use general preferences.\n"
                + json.dumps(
                    [{"title": item.job.title, "jd_raw": item.job.jd_raw}
                     for item in request.interests], ensure_ascii=False,
                )
            )
            selection = PreferenceLearner(preference_provider).select(
                memory, task="greeting", job_id=job, context=context,
            )
            request = GreetingRequest.model_validate(
                {**request.model_dump(), "preference_memory": selection.model_dump()},
            )
        destination.mkdir(parents=True, exist_ok=False)
        request_path = destination / "request.json"
        request_path.write_text(request.model_dump_json(indent=2), encoding="utf-8")
        report = GreetingGenerator(CodexGreetingProvider(model)).generate(request)
        report_path = destination / "report.json"
        report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        drafts_path = None
        if report.status == "passed" and report.outreach_draft is not None:
            drafts_path = destination / "drafts.json"
            drafts_path.write_text(
                json.dumps(
                    [report.outreach_draft.model_dump(mode="json")], ensure_ascii=False, indent=2
                ),
                encoding="utf-8",
            )
        typer.echo(
            json.dumps(
                {
                    "status": report.status,
                    "mode": report.mode,
                    "model": MODEL,
                    "input_digest": report.input_digest,
                    "report_path": str(report_path),
                    "request_path": str(request_path),
                    "drafts_path": str(drafts_path) if drafts_path else None,
                    "memory_version": request.preference_memory.memory_version
                    if request.preference_memory else None,
                    "approval_granted": False,
                    "dynamic_rules_version": request.dynamic_rules_version,
                },
                ensure_ascii=False,
            )
        )
        if report.status == "rejected":
            raise typer.Exit(code=1)
    except JobAgentError as error:
        typer.echo(
            json.dumps(
                {"error": {"code": error.code, "message": error.message, "details": error.details}},
                ensure_ascii=False,
            )
        )
        raise typer.Exit(code=1) from None
    except (OSError, ValidationError):
        typer.echo(
            json.dumps(
                {
                    "error": {
                        "code": "CONTRACT_VALIDATION_ERROR",
                        "message": "Greeting artifacts could not be validated or stored privately.",
                    }
                }
            )
        )
        raise typer.Exit(code=1) from None
