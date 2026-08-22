import pytest
from pydantic import ValidationError

from jobagent.schemas.optimizer_registry import (
    CapabilityFailurePolicy,
    CapabilityIndexDocument,
    CapabilityIndexEntry,
    CapabilityKind,
    CapabilityPermission,
    CapabilityPermissions,
    CapabilityRegistrySnapshot,
    FailureFallback,
    RetryMode,
    TrustLevel,
)


def capability_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": "repo.candidate.detect-gaps",
        "version": "1.0.0",
        "kind": "capability",
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
    return payload


def capability_entry(**overrides: object) -> CapabilityIndexEntry:
    return CapabilityIndexEntry.model_validate(capability_payload(**overrides))


def test_executable_entry_requires_entrypoint_and_contracts() -> None:
    with pytest.raises(ValidationError, match="entrypoint"):
        capability_entry(entrypoint=None)


def test_executable_entry_requires_a_produced_artifact() -> None:
    with pytest.raises(ValidationError, match="produces"):
        capability_entry(produces=[])


@pytest.mark.parametrize("kind", ["policy", "prompt-pack"])
def test_non_executable_entry_forbids_input_and_output_contracts(kind: str) -> None:
    with pytest.raises(ValidationError, match="input_schema and output_schema"):
        capability_entry(
            id=f"policy.optimizer.{kind}",
            kind=kind,
            input_schema="UnexpectedInput",
            output_schema="UnexpectedOutput",
            produces=[],
        )


def test_policy_cannot_request_write_permission() -> None:
    with pytest.raises(ValidationError, match="non-executable entries cannot write"):
        capability_entry(
            id="policy.optimizer.workflow",
            kind="policy",
            entrypoint="references/optimizer/workflow.md",
            input_schema=None,
            output_schema=None,
            permissions={"read": [], "write": ["canonical_evidence"]},
            produces=[],
        )


def test_role_is_not_part_of_the_approved_contract() -> None:
    with pytest.raises(ValidationError, match="role"):
        capability_entry(role="enrich")


@pytest.mark.parametrize(
    "bad_id",
    ["DetectGaps", "repo/detect-gaps", "repo..detect-gaps", "repo.Detect-gaps"],
)
def test_id_must_be_stable_lowercase_namespace(bad_id: str) -> None:
    with pytest.raises(ValidationError):
        capability_entry(id=bad_id)


@pytest.mark.parametrize("version", ["1.2.3-alpha.1", "1.2.3+build.5", "1.2.3-rc.1+sha.abc"])
def test_semver_supports_prerelease_and_build_metadata(version: str) -> None:
    assert capability_entry(version=version).version == version


def test_registry_strings_are_stripped_and_description_is_bounded() -> None:
    description = (
        "  Detect missing candidate knowledge for rewriting. "
        "Output CandidateGap records only; do not create evidence.  "
    )
    entry = capability_entry(
        id="  repo.candidate.detect-gaps  ",
        version="  1.0.0  ",
        description=description,
        entrypoint="  jobagent.candidate.gaps:GapDetector.detect  ",
        input_schema="  CandidateGapDetectionInput  ",
        output_schema="  CandidateGapSet  ",
        intents=["  detect_evidence_gap  "],
        required_context=["  candidate_profile  "],
        preconditions=["  explicit_user_confirmation  "],
        dependencies=["  repo.candidate.parse-resume  "],
        produces=["  CandidateGap  "],
        verifiers=["  repo.optimizer.verify  "],
    )

    assert entry.id == "repo.candidate.detect-gaps"
    assert entry.version == "1.0.0"
    assert entry.description == description.strip()
    assert entry.entrypoint == "jobagent.candidate.gaps:GapDetector.detect"
    assert entry.input_schema == "CandidateGapDetectionInput"
    assert entry.output_schema == "CandidateGapSet"
    assert entry.intents == ("detect_evidence_gap",)
    assert entry.required_context == ("candidate_profile",)
    assert entry.preconditions == ("explicit_user_confirmation",)
    assert entry.dependencies == ("repo.candidate.parse-resume",)
    assert entry.produces == ("CandidateGap",)
    assert entry.verifiers == ("repo.optimizer.verify",)

    with pytest.raises(ValidationError):
        capability_entry(description="x" * 501)


@pytest.mark.parametrize(
    "permission",
    [
        "unknown_resource",
        "application_send",
        "approval",
        "delivery",
        "connector",
        "browser",
        "authentication",
        "captcha",
    ],
)
def test_permissions_reject_unknown_and_forbidden_resources(permission: str) -> None:
    with pytest.raises(ValidationError):
        capability_entry(permissions={"read": [permission], "write": []})


def test_failure_policy_rejects_unapproved_fallback() -> None:
    with pytest.raises(ValidationError):
        capability_entry(failure_policy={"retry": "never", "fallback": "bypass_verifier"})


@pytest.mark.parametrize(
    "required_field",
    [
        "required_context",
        "preconditions",
        "dependencies",
        "produces",
        "verifiers",
        "failure_policy",
    ],
)
def test_spec_required_entry_fields_have_no_defaults(required_field: str) -> None:
    payload = capability_payload()
    del payload[required_field]

    with pytest.raises(ValidationError, match=required_field):
        CapabilityIndexEntry.model_validate(payload)


def test_document_requires_explicit_supported_version_and_entries() -> None:
    entry = capability_entry().model_dump(mode="json")

    with pytest.raises(ValidationError, match="schema_version"):
        CapabilityIndexDocument.model_validate({"entries": [entry]})
    with pytest.raises(ValidationError, match="schema_version"):
        CapabilityIndexDocument.model_validate({"schema_version": "2.0", "entries": [entry]})
    with pytest.raises(ValidationError, match="entries"):
        CapabilityIndexDocument.model_validate({"schema_version": "1.0", "entries": []})


def test_snapshot_rejects_duplicate_ids() -> None:
    entry = capability_entry()
    digest = "sha256:" + "a" * 64
    with pytest.raises(ValidationError, match="duplicate capability id"):
        CapabilityRegistrySnapshot(entries=[entry, entry], digest=digest)


@pytest.mark.parametrize(
    "digest",
    ["sha256:abc", "sha256:" + "A" * 64, "md5:" + "a" * 64, "sha256:" + "a" * 65],
)
def test_snapshot_requires_exact_lowercase_sha256_digest(digest: str) -> None:
    with pytest.raises(ValidationError):
        CapabilityRegistrySnapshot(entries=[capability_entry()], digest=digest)


def test_snapshot_graph_is_frozen_and_uses_tuples() -> None:
    entry = capability_entry()
    snapshot = CapabilityRegistrySnapshot(entries=[entry], digest="sha256:" + "a" * 64)

    assert isinstance(snapshot.entries, tuple)
    assert isinstance(entry.intents, tuple)
    assert isinstance(entry.permissions.read, tuple)
    with pytest.raises(AttributeError):
        entry.permissions.read.append(CapabilityPermission.CANDIDATE_PROFILE)  # type: ignore[attr-defined]
    with pytest.raises(ValidationError, match="frozen"):
        entry.description = "A replacement description that must be rejected after validation."
    with pytest.raises(ValidationError, match="frozen"):
        entry.permissions.write = (CapabilityPermission.CANONICAL_EVIDENCE,)
    with pytest.raises(ValidationError, match="frozen"):
        snapshot.entries = ()


def test_public_enums_are_stable() -> None:
    assert {item.value for item in CapabilityKind} == {
        "capability",
        "policy",
        "prompt-pack",
        "lens",
    }
    assert {item.value for item in CapabilityPermission} == {
        "candidate_profile",
        "candidate_evidence",
        "resume_source",
        "resume_item",
        "evidence_summary",
        "target_role",
        "job_record",
        "job_requirements",
        "requirement_matches",
        "job_intelligence",
        "interview_event",
        "draft_evidence",
        "canonical_evidence",
        "optimizer_contracts",
        "optimization_session",
        "perspective_finding",
        "strategy_proposal",
        "rewrite_proposal",
        "verification_finding",
        "user_feedback",
        "policy_resource",
        "prompt_resource",
        "claim_ledger",
        "resume_diff",
        "compatibility_report",
    }
    assert {item.value for item in FailureFallback} == {
        "return_typed_failure",
        "pause_for_human",
        "quarantine_capability",
    }
    assert {item.value for item in TrustLevel} == {"core", "project", "third_party"}
    assert {item.value for item in RetryMode} == {"never", "transient_once"}
    assert CapabilityPermissions(read=[], write=[]).write == ()
    failure_policy = CapabilityFailurePolicy(
        retry="never", fallback="return_typed_failure"
    )
    assert failure_policy.retry is RetryMode.NEVER
    assert failure_policy.fallback is FailureFallback.RETURN_TYPED_FAILURE
