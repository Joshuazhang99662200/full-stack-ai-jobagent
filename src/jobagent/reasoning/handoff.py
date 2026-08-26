"""Reasoning that defers to the calling coding agent instead of a model API.

`AgentHandoffProvider` implements the same `ReasoningProvider` port as the API
provider, so every reasoning-backed capability works in agent mode without any
vendor credentials. Rather than returning a result, it writes a complete request
and raises `AgentHandoffRequiredError`. The agent produces the requested contract
and re-enters through a typed-input command.

This keeps the evidence rules intact: the agent's output is validated against the
same contract, and extracted evidence still arrives unconfirmed.
"""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jobagent.capabilities import ReasoningOutputT
from jobagent.errors import AgentHandoffRequiredError, ContractValidationError
from jobagent.reasoning.prompts import registered_prompt_ids, system_prompt
from jobagent.schemas.reasoning import ReasoningHandoffRequest

# How the agent resumes the workflow once it has written the requested contract.
_RESUME_COMMANDS = {
    "candidate.extract_draft.v1": "jobagent candidate import-draft {output_path}",
    "job.requirements.extract.v1": "jobagent jobs requirements {job_id} {output_path}",
    "job.match.evidence.v1": "jobagent jobs match {job_id} <requirements.json> {output_path}",
    "resume.tailor.v1": "jobagent optimizer assemble {output_path} --variant-id <VARIANT_ID>",
}


class AgentHandoffProvider:
    """Emit a typed reasoning request for the calling agent to satisfy."""

    def __init__(self, handoff_dir: Path) -> None:
        self._handoff_dir = handoff_dir

    def generate(
        self,
        *,
        prompt_id: str,
        context: Mapping[str, Any],
        output_type: type[ReasoningOutputT],
    ) -> ReasoningOutputT:
        instructions = system_prompt(prompt_id)
        if instructions is None:
            raise ContractValidationError(
                "No runtime prompt is registered for this prompt ID.",
                details={"prompt_id": prompt_id, "known": list(registered_prompt_ids())},
            )

        self._handoff_dir.mkdir(parents=True, exist_ok=True)
        output_path = self._handoff_dir / f"{prompt_id}.output.json"
        request = ReasoningHandoffRequest(
            prompt_id=prompt_id,
            output_contract=output_type.__name__,
            instructions=instructions,
            context=dict(context),
            output_schema=output_type.model_json_schema(),
            output_path=str(output_path),
            resume_command=self._resume_command(prompt_id, context, output_path),
        )
        request_path = self._handoff_dir / f"{prompt_id}.request.json"
        request_path.write_text(
            request.model_dump_json(indent=2),
            encoding="utf-8",
        )

        raise AgentHandoffRequiredError(
            "This reasoning step is delegated to the calling agent.",
            details={
                "prompt_id": prompt_id,
                "request_path": str(request_path),
                "output_path": str(output_path),
                "output_contract": output_type.__name__,
                "resume_command": request.resume_command,
            },
        )

    @staticmethod
    def _resume_command(
        prompt_id: str, context: Mapping[str, Any], output_path: Path
    ) -> str:
        template = _RESUME_COMMANDS.get(prompt_id, "jobagent <resume-command> {output_path}")
        return template.format(
            output_path=output_path,
            job_id=context.get("job_id", "<job-id>"),
        )


def load_handoff_output(path: Path, output_type: type[ReasoningOutputT]) -> ReasoningOutputT:
    """Validate agent-written output against the contract it was asked to produce."""
    try:
        payload = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ContractValidationError(
            "The agent handoff output file could not be read.",
            details={"path": str(path), "contract": output_type.__name__},
        ) from error
    try:
        return output_type.model_validate_json(payload)
    except ValueError as error:
        raise ContractValidationError(
            "The agent handoff output did not satisfy its contract.",
            details={"path": str(path), "contract": output_type.__name__},
        ) from error


def write_json(path: Path, payload: Any) -> None:
    """Helper for tests and tooling that stage agent output."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
