"""Claude-backed implementation of the structured reasoning port.

This is the only vendor-aware module in the reasoning layer. It converts a
`prompt_id` plus typed context into one structured Claude call and returns the
validated contract model, so domain code stays provider-neutral.
"""

import json
from typing import TYPE_CHECKING, Any, Literal

from pydantic import ValidationError

from jobagent.capabilities import ReasoningOutputT
from jobagent.errors import (
    ContractValidationError,
    InvalidProviderOutputError,
    UserInterventionRequiredError,
)
from jobagent.reasoning.prompts import registered_prompt_ids, system_prompt

if TYPE_CHECKING:  # pragma: no cover - import used for typing only
    from collections.abc import Mapping

Effort = Literal["low", "medium", "high", "xhigh", "max"]

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_MAX_TOKENS = 16000
DEFAULT_EFFORT: Effort = "high"


class ClaudeReasoningProvider:
    """Structured extraction through the Claude Messages API."""

    def __init__(
        self,
        *,
        client: Any | None = None,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        effort: Effort = DEFAULT_EFFORT,
    ) -> None:
        if client is None:
            try:
                import anthropic
            except ImportError as error:  # pragma: no cover - depends on install extras
                raise UserInterventionRequiredError(
                    "The anthropic SDK is not installed. Install jobagent with the "
                    "'reasoning' extra to enable model-backed extraction.",
                    details={"package": "anthropic"},
                ) from error
            client = anthropic.Anthropic()
        self._client = client
        self._model = model
        self._max_tokens = max_tokens
        self._effort = effort

    def generate(
        self,
        *,
        prompt_id: str,
        context: "Mapping[str, Any]",
        output_type: type[ReasoningOutputT],
    ) -> ReasoningOutputT:
        prompt = system_prompt(prompt_id)
        if prompt is None:
            raise ContractValidationError(
                "No runtime prompt is registered for this prompt ID.",
                details={"prompt_id": prompt_id, "known": list(registered_prompt_ids())},
            )

        message = self._call(prompt_id, prompt, context, output_type)

        if message.stop_reason == "refusal":
            details = getattr(message, "stop_details", None)
            raise UserInterventionRequiredError(
                "Claude declined this request; a human must review the input.",
                details={
                    "prompt_id": prompt_id,
                    "category": getattr(details, "category", None),
                },
            )
        if message.stop_reason == "max_tokens":
            raise InvalidProviderOutputError(
                "Claude hit the output limit before completing the structured result.",
                details={"prompt_id": prompt_id, "max_tokens": self._max_tokens},
            )

        parsed = self._parsed_output(message)
        if parsed is None:
            raise InvalidProviderOutputError(
                "Claude returned no structured output.",
                details={"prompt_id": prompt_id, "stop_reason": message.stop_reason},
            )
        try:
            return output_type.model_validate(parsed)
        except ValidationError as error:
            raise InvalidProviderOutputError(
                "Claude output did not satisfy the requested contract.",
                details={"prompt_id": prompt_id, "output_type": output_type.__name__},
            ) from error

    def _call(
        self,
        prompt_id: str,
        prompt: str,
        context: "Mapping[str, Any]",
        output_type: type[ReasoningOutputT],
    ) -> Any:
        try:
            return self._client.messages.parse(
                model=self._model,
                max_tokens=self._max_tokens,
                system=prompt,
                messages=[
                    {
                        "role": "user",
                        "content": json.dumps(dict(context), ensure_ascii=False, sort_keys=True),
                    }
                ],
                output_format=output_type,
                thinking={"type": "adaptive"},
                output_config={"effort": self._effort},
            )
        except Exception as error:
            raise self._translated(prompt_id, error) from error

    @staticmethod
    def _parsed_output(message: Any) -> Any:
        for block in getattr(message, "content", ()) or ():
            parsed = getattr(block, "parsed_output", None)
            if parsed is not None:
                return parsed
        return None

    @staticmethod
    def _translated(prompt_id: str, error: Exception) -> Exception:
        name = type(error).__name__
        # Auth, quota and rate limits are not transient decoding faults; they need
        # a person to act, so they must not be retried inside the workflow.
        if name in {
            "AuthenticationError",
            "PermissionDeniedError",
            "RateLimitError",
            "APIConnectionError",
            "APITimeoutError",
        }:
            return UserInterventionRequiredError(
                "The Claude API is not usable right now; a human must resolve it.",
                details={"prompt_id": prompt_id, "reason": name},
            )
        status = getattr(error, "status_code", None)
        if isinstance(status, int) and status >= 500:
            return UserInterventionRequiredError(
                "The Claude API reported a server error.",
                details={"prompt_id": prompt_id, "status_code": status},
            )
        if isinstance(error, ContractValidationError | InvalidProviderOutputError):
            return error
        return InvalidProviderOutputError(
            "The Claude API call failed.",
            details={"prompt_id": prompt_id, "reason": name},
        )
