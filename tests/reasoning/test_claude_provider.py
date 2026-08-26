from typing import Any

import pytest

from jobagent.capabilities import ReasoningProvider
from jobagent.errors import (
    ContractValidationError,
    InvalidProviderOutputError,
    UserInterventionRequiredError,
)
from jobagent.reasoning.claude import ClaudeReasoningProvider
from jobagent.reasoning.prompts import system_prompt
from jobagent.schemas.candidate import CandidateDraft, CandidateProfile

DRAFT = CandidateDraft(candidate_id="CAND_001", profile=CandidateProfile(id="CAND_001"))


class FakeBlock:
    def __init__(self, parsed_output: Any) -> None:
        self.parsed_output = parsed_output


class FakeMessage:
    def __init__(
        self,
        *,
        content: list[Any] | None = None,
        stop_reason: str = "end_turn",
        stop_details: Any = None,
    ) -> None:
        self.content = content or []
        self.stop_reason = stop_reason
        self.stop_details = stop_details


class FakeMessages:
    def __init__(self, result: Any) -> None:
        self._result = result
        self.calls: list[dict[str, Any]] = []

    def parse(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class FakeClient:
    def __init__(self, result: Any) -> None:
        self.messages = FakeMessages(result)


def provider_for(result: Any) -> tuple[ClaudeReasoningProvider, FakeClient]:
    client = FakeClient(result)
    return ClaudeReasoningProvider(client=client), client


def test_provider_satisfies_the_reasoning_port() -> None:
    provider, _ = provider_for(FakeMessage())
    assert isinstance(provider, ReasoningProvider)


def test_structured_output_is_validated_into_the_requested_contract() -> None:
    message = FakeMessage(content=[FakeBlock(DRAFT.model_dump(mode="json"))])
    provider, client = provider_for(message)

    result = provider.generate(
        prompt_id="candidate.extract_draft.v1",
        context={"candidate_id": "CAND_001"},
        output_type=CandidateDraft,
    )

    assert isinstance(result, CandidateDraft)
    assert result.candidate_id == "CAND_001"

    call = client.messages.calls[0]
    assert call["model"] == "claude-opus-5"
    assert call["output_format"] is CandidateDraft
    assert call["thinking"] == {"type": "adaptive"}
    assert call["output_config"] == {"effort": "high"}
    assert "budget_tokens" not in str(call)


def test_unknown_prompt_id_is_rejected_before_any_api_call() -> None:
    provider, client = provider_for(FakeMessage())

    with pytest.raises(ContractValidationError) as caught:
        provider.generate(prompt_id="nope.v1", context={}, output_type=CandidateDraft)

    assert client.messages.calls == []
    assert "candidate.extract_draft.v1" in caught.value.details["known"]


def test_refusal_stops_for_a_human() -> None:
    class Details:
        category = "cyber"

    message = FakeMessage(stop_reason="refusal", stop_details=Details())
    provider, _ = provider_for(message)

    with pytest.raises(UserInterventionRequiredError) as caught:
        provider.generate(
            prompt_id="candidate.extract_draft.v1", context={}, output_type=CandidateDraft
        )

    assert caught.value.details["category"] == "cyber"


def test_truncated_output_is_not_treated_as_a_result() -> None:
    message = FakeMessage(
        content=[FakeBlock(DRAFT.model_dump(mode="json"))], stop_reason="max_tokens"
    )
    provider, _ = provider_for(message)

    with pytest.raises(InvalidProviderOutputError, match="output limit"):
        provider.generate(
            prompt_id="candidate.extract_draft.v1", context={}, output_type=CandidateDraft
        )


def test_missing_structured_output_is_an_error_not_an_empty_draft() -> None:
    provider, _ = provider_for(FakeMessage(content=[]))

    with pytest.raises(InvalidProviderOutputError, match="no structured output"):
        provider.generate(
            prompt_id="candidate.extract_draft.v1", context={}, output_type=CandidateDraft
        )


def test_output_violating_the_contract_is_rejected() -> None:
    message = FakeMessage(content=[FakeBlock({"candidate_id": "not-an-id"})])
    provider, _ = provider_for(message)

    with pytest.raises(InvalidProviderOutputError, match="did not satisfy"):
        provider.generate(
            prompt_id="candidate.extract_draft.v1", context={}, output_type=CandidateDraft
        )


@pytest.mark.parametrize(
    "name", ["AuthenticationError", "RateLimitError", "APIConnectionError", "APITimeoutError"]
)
def test_platform_failures_require_a_human_and_are_not_retried(name: str) -> None:
    error = type(name, (Exception,), {})()
    provider, _ = provider_for(error)

    with pytest.raises(UserInterventionRequiredError) as caught:
        provider.generate(
            prompt_id="candidate.extract_draft.v1", context={}, output_type=CandidateDraft
        )

    assert caught.value.details["reason"] == name


def test_server_error_requires_a_human() -> None:
    error = type("APIStatusError", (Exception,), {"status_code": 503})()
    provider, _ = provider_for(error)

    with pytest.raises(UserInterventionRequiredError) as caught:
        provider.generate(
            prompt_id="candidate.extract_draft.v1", context={}, output_type=CandidateDraft
        )

    assert caught.value.details["status_code"] == 503


def test_provider_sends_the_composed_instructions_as_the_system_prompt() -> None:
    message = FakeMessage(content=[FakeBlock(DRAFT.model_dump(mode="json"))])
    provider, client = provider_for(message)

    provider.generate(
        prompt_id="candidate.extract_draft.v1",
        context={"candidate_id": "CAND_001"},
        output_type=CandidateDraft,
    )

    assert client.messages.calls[0]["system"] == system_prompt("candidate.extract_draft.v1")
