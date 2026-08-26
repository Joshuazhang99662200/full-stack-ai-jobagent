import json
from pathlib import Path

import pytest

from jobagent.capabilities import ReasoningProvider
from jobagent.errors import AgentHandoffRequiredError, ContractValidationError
from jobagent.reasoning.handoff import AgentHandoffProvider, load_handoff_output
from jobagent.schemas.candidate import CandidateDraft, CandidateProfile
from jobagent.schemas.reasoning import ReasoningHandoffRequest

CONTEXT = {"candidate_id": "CAND_001", "pages": [{"page_number": 1, "text": "Experience"}]}


def test_provider_satisfies_the_reasoning_port(tmp_path: Path) -> None:
    assert isinstance(AgentHandoffProvider(tmp_path), ReasoningProvider)


def test_handoff_needs_no_credentials_and_emits_a_self_contained_request(
    tmp_path: Path,
) -> None:
    provider = AgentHandoffProvider(tmp_path)

    with pytest.raises(AgentHandoffRequiredError) as caught:
        provider.generate(
            prompt_id="candidate.extract_draft.v1",
            context=CONTEXT,
            output_type=CandidateDraft,
        )

    assert caught.value.code == "AGENT_HANDOFF_REQUIRED"
    request_path = Path(caught.value.details["request_path"])
    request = ReasoningHandoffRequest.model_validate_json(
        request_path.read_text(encoding="utf-8")
    )

    # Everything the agent needs must be in the file — instructions, source
    # context, and the exact schema of the contract to produce.
    assert request.output_contract == "CandidateDraft"
    assert request.context == CONTEXT
    assert request.instructions.strip()
    assert request.output_schema["$defs"]
    assert request.output_path.endswith("candidate.extract_draft.v1.output.json")


def test_resume_command_tells_the_agent_how_to_re_enter(tmp_path: Path) -> None:
    provider = AgentHandoffProvider(tmp_path)

    with pytest.raises(AgentHandoffRequiredError) as caught:
        provider.generate(
            prompt_id="candidate.extract_draft.v1",
            context=CONTEXT,
            output_type=CandidateDraft,
        )

    assert caught.value.details["resume_command"].startswith("jobagent candidate import-draft")


def test_job_prompt_resume_command_carries_the_job_id(tmp_path: Path) -> None:
    provider = AgentHandoffProvider(tmp_path)

    with pytest.raises(AgentHandoffRequiredError) as caught:
        provider.generate(
            prompt_id="job.requirements.extract.v1",
            context={"job_id": "JOB_123"},
            output_type=CandidateDraft,
        )

    assert "JOB_123" in caught.value.details["resume_command"]


def test_unknown_prompt_id_is_rejected_without_writing_a_request(tmp_path: Path) -> None:
    provider = AgentHandoffProvider(tmp_path)

    with pytest.raises(ContractValidationError):
        provider.generate(prompt_id="nope.v1", context={}, output_type=CandidateDraft)

    assert list(tmp_path.glob("*.json")) == []


def test_agent_output_is_validated_against_its_contract(tmp_path: Path) -> None:
    draft = CandidateDraft(candidate_id="CAND_001", profile=CandidateProfile(id="CAND_001"))
    path = tmp_path / "output.json"
    path.write_text(draft.model_dump_json(), encoding="utf-8")

    assert load_handoff_output(path, CandidateDraft) == draft


def test_agent_output_violating_the_contract_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "output.json"
    path.write_text(json.dumps({"candidate_id": "not-an-id"}), encoding="utf-8")

    with pytest.raises(ContractValidationError, match="did not satisfy"):
        load_handoff_output(path, CandidateDraft)


def test_missing_agent_output_is_reported_clearly(tmp_path: Path) -> None:
    with pytest.raises(ContractValidationError, match="could not be read"):
        load_handoff_output(tmp_path / "absent.json", CandidateDraft)


def test_agent_cannot_hand_back_pre_confirmed_evidence(tmp_path: Path) -> None:
    """The draft contract forbids confirmed evidence, so a handoff cannot smuggle it."""
    path = tmp_path / "output.json"
    path.write_text(
        json.dumps(
            {
                "candidate_id": "CAND_001",
                "profile": {"id": "CAND_001"},
                "evidence": [
                    {
                        "id": "EVID_1",
                        "type": "experience",
                        "statement": "Led a migration.",
                        "source": {"type": "resume", "reference": "RESUME_1:page:1"},
                        "confidence": "explicit",
                        "user_confirmed": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ContractValidationError):
        load_handoff_output(path, CandidateDraft)
