import pytest
from pydantic import ValidationError

from jobagent.schemas.optimizer_registry import (
    CapabilityFailurePolicy,
    CapabilityIndexEntry,
    CapabilityKind,
    CapabilityPermissions,
    CapabilityRegistrySnapshot,
    CapabilityRole,
    RetryMode,
    TrustLevel,
)


def capability_entry(**overrides: object) -> CapabilityIndexEntry:
    payload: dict[str, object] = {
        "id": "repo.candidate.detect-gaps",
        "version": "1.0.0",
        "kind": "capability",
        "role": "enrich",
        "description": (
            "Detect missing or weak candidate knowledge before rewriting. "
            "Output CandidateGap records only; do not create or confirm evidence."
        ),
        "entrypoint": "jobagent.candidate.gaps:GapDetector.detect",
        "input_schema": "CandidateGapDetectionInput",
        "output_schema": "CandidateGapSet",
        "intents": ["detect_evidence_gap"],
        "required_context": ["candidate_profile", "evidence_summary"],
        "permissions": {"read": ["candidate_profile", "candidate_evidence"], "write": []},
        "preconditions": [],
        "dependencies": [],
        "produces": ["CandidateGap"],
        "verifiers": [],
        "failure_policy": {"retry": "never", "fallback": "return_typed_failure"},
        "trust": "core",
    }
    payload.update(overrides)
    return CapabilityIndexEntry.model_validate(payload)


def test_executable_entry_requires_entrypoint_and_contracts() -> None:
    with pytest.raises(ValidationError, match="entrypoint"):
        capability_entry(entrypoint=None)


def test_policy_cannot_request_write_permission() -> None:
    with pytest.raises(ValidationError, match="non-executable entries cannot write"):
        capability_entry(
            id="policy.optimizer.workflow",
            kind="policy",
            role="support",
            entrypoint="references/optimizer/workflow.md",
            input_schema=None,
            output_schema=None,
            permissions={"read": [], "write": ["canonical_evidence"]},
        )


@pytest.mark.parametrize(
    "bad_id",
    ["DetectGaps", "repo/detect-gaps", "repo..detect-gaps", " repo.detect-gaps"],
)
def test_id_must_be_stable_lowercase_namespace(bad_id: str) -> None:
    with pytest.raises(ValidationError):
        capability_entry(id=bad_id)


def test_snapshot_rejects_duplicate_ids() -> None:
    entry = capability_entry()
    with pytest.raises(ValidationError, match="duplicate capability id"):
        CapabilityRegistrySnapshot(entries=[entry, entry], digest="sha256:abc")


def test_public_enums_are_stable() -> None:
    assert {item.value for item in CapabilityKind} == {
        "capability",
        "policy",
        "prompt-pack",
        "lens",
    }
    assert {item.value for item in CapabilityRole} == {
        "analyze",
        "enrich",
        "strategy",
        "rewrite",
        "verify",
        "interaction",
        "support",
    }
    assert {item.value for item in TrustLevel} == {"core", "project", "third_party"}
    assert {item.value for item in RetryMode} == {"never", "transient_once"}
    assert CapabilityPermissions(read=[], write=[]).write == []
    assert CapabilityFailurePolicy().retry is RetryMode.NEVER
