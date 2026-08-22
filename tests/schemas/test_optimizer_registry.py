import pytest
from pydantic import ValidationError

from jobagent.schemas.optimizer_registry import (
    CapabilityFailurePolicy,
    CapabilityIndexDocument,
    CapabilityIndexEntry,
    CapabilityKind,
    CapabilityPermissions,
    CapabilityReadPermission,
    CapabilityRegistrySnapshot,
    CapabilityWritePermission,
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


def test_third_party_cannot_write_canonical_evidence() -> None:
    with pytest.raises(ValidationError, match="trust core"):
        capability_entry(
            id="repo.candidate.confirm-evidence",
            kind="lens",
            trust="third_party",
            permissions={"read": ["candidate_evidence"], "write": ["canonical_evidence"]},
            preconditions=["explicit_user_confirmation"],
        )


def test_write_permissions_reject_read_only_candidate_profile() -> None:
    with pytest.raises(ValidationError, match="candidate_profile"):
        capability_entry(
            id="plugin.example.profile-writer",
            kind="lens",
            trust="third_party",
            permissions={"read": [], "write": ["candidate_profile"]},
        )


def test_core_non_confirmation_capability_cannot_write_canonical_evidence() -> None:
    with pytest.raises(ValidationError, match=r"repo\.candidate\.confirm-evidence"):
        capability_entry(
            id="repo.candidate.detect-gaps",
            trust="core",
            permissions={"read": ["candidate_evidence"], "write": ["canonical_evidence"]},
            preconditions=["explicit_user_confirmation"],
        )


def test_confirmation_capability_requires_explicit_user_confirmation() -> None:
    with pytest.raises(ValidationError, match="explicit_user_confirmation"):
        capability_entry(
            id="repo.candidate.confirm-evidence",
            trust="core",
            permissions={"read": ["draft_evidence"], "write": ["canonical_evidence"]},
            preconditions=[],
        )


def test_core_confirmation_capability_may_write_canonical_evidence() -> None:
    entry = capability_entry(
        id="repo.candidate.confirm-evidence",
        trust="core",
        permissions={"read": ["draft_evidence"], "write": ["canonical_evidence"]},
        preconditions=["explicit_user_confirmation"],
    )

    assert entry.permissions.write == (CapabilityWritePermission.CANONICAL_EVIDENCE,)


@pytest.mark.parametrize(
    "permission",
    [
        "interview_event",
        "draft_evidence",
        "optimization_session",
        "claim_ledger",
        "resume_diff",
        "compatibility_report",
    ],
)
def test_untrusted_capability_cannot_write_core_state(permission: str) -> None:
    with pytest.raises(ValidationError, match="project and third_party"):
        capability_entry(
            id="plugin.example.state-writer",
            kind="lens",
            trust="third_party",
            permissions={"read": [], "write": [permission]},
        )


def test_third_party_lens_may_write_perspective_finding() -> None:
    entry = capability_entry(
        id="plugin.example.perspective-lens",
        kind="lens",
        trust="third_party",
        permissions={"read": ["candidate_profile"], "write": ["perspective_finding"]},
        produces=["PerspectiveFinding"],
    )

    assert entry.permissions.write == (CapabilityWritePermission.PERSPECTIVE_FINDING,)


def test_core_capability_may_write_job_intelligence_artifacts() -> None:
    entry = capability_entry(
        id="repo.jobs.refresh-intelligence",
        trust="core",
        permissions={"read": ["job_record"], "write": ["job_intelligence"]},
        produces=["JobIntelligenceRun"],
    )

    assert entry.permissions.write == (CapabilityWritePermission.JOB_INTELLIGENCE,)


def test_third_party_cannot_write_job_intelligence_artifacts() -> None:
    with pytest.raises(ValidationError, match="project and third_party"):
        capability_entry(
            id="plugin.example.intelligence-writer",
            kind="lens",
            trust="third_party",
            permissions={"read": ["job_record"], "write": ["job_intelligence"]},
            produces=["JobIntelligenceRun"],
        )


def test_candidate_gap_is_an_approved_read_permission() -> None:
    permissions = CapabilityPermissions(read=["candidate_gap"], write=[])

    assert permissions.read == (CapabilityReadPermission.CANDIDATE_GAP,)


def test_candidate_gap_is_not_an_approved_write_permission() -> None:
    with pytest.raises(ValidationError, match="candidate_gap"):
        CapabilityPermissions(read=[], write=["candidate_gap"])


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
        entry.permissions.read.append(  # type: ignore[attr-defined]
            CapabilityReadPermission.CANDIDATE_PROFILE
        )
    with pytest.raises(ValidationError, match="frozen"):
        entry.description = "A replacement description that must be rejected after validation."
    with pytest.raises(ValidationError, match="frozen"):
        entry.permissions.write = (CapabilityWritePermission.CANONICAL_EVIDENCE,)
    with pytest.raises(ValidationError, match="frozen"):
        snapshot.entries = ()


def test_public_enums_are_stable() -> None:
    assert {item.value for item in CapabilityKind} == {
        "capability",
        "policy",
        "prompt-pack",
        "lens",
    }
    assert {item.value for item in CapabilityReadPermission} == {
        "candidate_profile",
        "candidate_evidence",
        "candidate_gap",
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
    assert {item.value for item in CapabilityWritePermission} == {
        "interview_event",
        "draft_evidence",
        "canonical_evidence",
        "optimization_session",
        "perspective_finding",
        "strategy_proposal",
        "rewrite_proposal",
        "verification_finding",
        "claim_ledger",
        "resume_diff",
        "compatibility_report",
        "job_intelligence",
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
