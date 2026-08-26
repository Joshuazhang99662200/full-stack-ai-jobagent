"""Contracts for handing a reasoning step to the calling coding agent.

The agent running this repository is itself the reasoning engine, so a reasoning
step does not have to call a model API. Instead the workflow emits a complete,
self-contained request: the instructions, the source context, the exact JSON
Schema of the contract to produce, and where to write it. The agent writes that
file and re-enters the workflow through a normal typed-input command.
"""

from typing import Any

from pydantic import Field

from jobagent.schemas.common import ContractModel, NonEmptyString


class ReasoningHandoffRequest(ContractModel):
    """Everything the calling agent needs to satisfy one reasoning step."""

    prompt_id: NonEmptyString
    output_contract: NonEmptyString
    instructions: NonEmptyString
    context: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    output_path: NonEmptyString
    resume_command: NonEmptyString
