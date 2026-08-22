import importlib
from pathlib import Path

import pytest
import yaml

from jobagent.optimizer.index import CapabilityIndexLoader, CapabilityRegistryCompiler
from jobagent.schemas.optimizer_registry import (
    CapabilityKind,
    CapabilityRegistrySnapshot,
    CapabilityWritePermission,
    TrustLevel,
)

ROOT = Path(__file__).parents[2]
SKILL_ROOT = ROOT / "skills" / "job-hunting"
INDEX_PATHS = (
    Path("optimizer/index/repository.yaml"),
    Path("optimizer/index/policies.yaml"),
)

EXPECTED_IDS = {
    "repo.candidate.parse-resume",
    "repo.candidate.detect-gaps",
    "repo.candidate.ask-question",
    "repo.candidate.add-draft-evidence",
    "repo.candidate.confirm-evidence",
    "repo.jobs.extract-requirements",
    "repo.jobs.match-evidence",
    "repo.jobs.refresh-intelligence",
    "repo.optimizer.contracts",
    "policy.optimizer.workflow",
    "policy.optimizer.evidence",
    "policy.optimizer.prompt-routing",
    "policy.optimizer.quality-gates",
    "policy.optimizer.failure-handling",
}

REQUIRED_ENTRY_FIELDS = {
    "id",
    "version",
    "kind",
    "description",
    "entrypoint",
    "input_schema",
    "output_schema",
    "intents",
    "required_context",
    "permissions",
    "preconditions",
    "dependencies",
    "produces",
    "verifiers",
    "failure_policy",
    "trust",
}

FORBIDDEN_WORDS = {
    "apply",
    "application",
    "submission",
    "approval",
    "delivery",
    "connector",
    "authentication",
    "captcha",
    "login",
    "browser",
}

EXPECTED_POLICY_PATHS = {
    "policy.optimizer.workflow": "references/optimizer/workflow.md",
    "policy.optimizer.evidence": "references/optimizer/evidence-contract.md",
    "policy.optimizer.prompt-routing": "references/optimizer/prompt-routing.md",
    "policy.optimizer.quality-gates": "references/optimizer/quality-gates.md",
    "policy.optimizer.failure-handling": "references/optimizer/failure-handling.md",
}


def snapshot() -> CapabilityRegistrySnapshot:
    return CapabilityRegistryCompiler(CapabilityIndexLoader(SKILL_ROOT)).compile(
        INDEX_PATHS
    )


def test_repository_index_exposes_the_approved_initial_surface() -> None:
    entries = snapshot().entries
    assert {entry.id for entry in entries} == EXPECTED_IDS
    assert all(len(entry.description) >= 40 for entry in entries)
    permission_tokens = {
        permission.casefold()
        for entry in entries
        for permission in (*entry.permissions.read, *entry.permissions.write)
    }
    assert all(
        forbidden not in permission
        for permission in permission_tokens
        for forbidden in FORBIDDEN_WORDS
    )
    assert all(
        forbidden not in entry.id.casefold()
        for entry in entries
        for forbidden in FORBIDDEN_WORDS
    )
    for entry in entries:
        routing_tokens = (
            *entry.intents,
            *entry.required_context,
            *entry.preconditions,
            *entry.produces,
            entry.entrypoint,
        )
        assert all(
            forbidden not in token.casefold()
            for token in routing_tokens
            for forbidden in FORBIDDEN_WORDS
        )


def test_every_index_entry_declares_the_complete_reviewed_contract() -> None:
    for relative_path in INDEX_PATHS:
        payload = yaml.safe_load((SKILL_ROOT / relative_path).read_text(encoding="utf-8"))
        assert payload["schema_version"] == "1.0"
        for entry in payload["entries"]:
            assert set(entry) == REQUIRED_ENTRY_FIELDS
            assert "role" not in entry
            assert set(entry["permissions"]) == {"read", "write"}
            assert set(entry["failure_policy"]) == {"retry", "fallback"}
            for marker in ("Outcome:", "Trigger:", "Excludes:", "Output:"):
                assert marker in entry["description"]


def test_descriptions_state_an_explicit_exclusion_boundary() -> None:
    exclusion_terms = ("do not", "only", "cannot", "never")
    for entry in snapshot().entries:
        description = entry.description.casefold()
        exclusion = description.split("excludes:", maxsplit=1)[1].split(
            "output:", maxsplit=1
        )[0]
        assert any(term in exclusion for term in exclusion_terms), entry.id


def test_executable_entries_declare_routing_and_output_contracts() -> None:
    for entry in snapshot().entries:
        if entry.kind is not CapabilityKind.CAPABILITY:
            continue
        assert entry.intents, entry.id
        assert entry.produces, entry.id
        assert entry.entrypoint.count(":") == 1, entry.id
        module_name, attribute_path = entry.entrypoint.split(":")
        assert module_name, entry.id
        assert attribute_path, entry.id
        assert all(segment for segment in attribute_path.split(".")), entry.id


def test_confirm_evidence_is_the_only_canonical_writer() -> None:
    writers = tuple(
        entry
        for entry in snapshot().entries
        if "canonical_evidence" in entry.permissions.write
    )
    assert tuple(entry.id for entry in writers) == (
        "repo.candidate.confirm-evidence",
    )
    assert writers[0].trust is TrustLevel.CORE
    assert writers[0].preconditions == (
        "phase2_adapter_available",
        "explicit_user_confirmation",
    )


def test_ask_question_is_a_pure_selector() -> None:
    entry = next(
        entry
        for entry in snapshot().entries
        if entry.id == "repo.candidate.ask-question"
    )
    assert entry.permissions.write == ()
    assert entry.produces == ("InterviewQuestion",)
    assert entry.required_context == ("candidate_gap", "target_role", "recent_gap_ids")
    assert tuple(permission.value for permission in entry.permissions.read) == (
        "candidate_gap",
        "target_role",
    )


def test_detect_gaps_matches_the_repository_method_signature() -> None:
    entry = next(
        entry
        for entry in snapshot().entries
        if entry.id == "repo.candidate.detect-gaps"
    )
    assert entry.required_context == (
        "candidate_profile",
        "candidate_evidence",
        "target_role",
    )
    assert tuple(permission.value for permission in entry.permissions.read) == (
        "candidate_profile",
        "candidate_evidence",
        "target_role",
    )
    assert entry.produces == ("CandidateGap",)


def test_parse_resume_describes_its_typed_parser_result() -> None:
    entry = next(
        entry
        for entry in snapshot().entries
        if entry.id == "repo.candidate.parse-resume"
    )
    assert entry.produces == ("ParsedResume",)
    assert all(token in entry.description for token in ("pages", "warnings", "digest"))


def test_match_evidence_reads_the_owning_job_record() -> None:
    entry = next(
        entry
        for entry in snapshot().entries
        if entry.id == "repo.jobs.match-evidence"
    )
    assert "job_record" in entry.required_context
    assert "job_record" in entry.permissions.read
    assert "confirmed_evidence_available" not in entry.preconditions
    assert "job_requirements_available" in entry.preconditions


def test_executables_reference_the_minimum_policy_layer() -> None:
    executable_entries = tuple(
        entry
        for entry in snapshot().entries
        if entry.kind is CapabilityKind.CAPABILITY
    )
    for entry in executable_entries:
        assert any(
            dependency.startswith("policy.optimizer.")
            for dependency in entry.dependencies
        )
    referenced_policies = {
        dependency
        for entry in executable_entries
        for dependency in entry.dependencies
        if dependency.startswith("policy.optimizer.")
    }
    assert referenced_policies == set(EXPECTED_POLICY_PATHS)


def test_phase1_filters_every_future_adapter_contract() -> None:
    for entry in snapshot().entries:
        if entry.kind is not CapabilityKind.CAPABILITY:
            continue
        adapter_precondition = (
            "phase2_refresh_adapter_available"
            if entry.id == "repo.jobs.refresh-intelligence"
            else "phase2_adapter_available"
        )
        assert adapter_precondition in entry.preconditions


def test_policies_do_not_require_the_resource_they_are_loading() -> None:
    for entry in snapshot().entries:
        if entry.kind is CapabilityKind.POLICY:
            assert entry.required_context == ()


def test_refresh_intelligence_is_unavailable_phase1_write_metadata() -> None:
    entry = next(
        entry
        for entry in snapshot().entries
        if entry.id == "repo.jobs.refresh-intelligence"
    )
    assert entry.permissions.write == (CapabilityWritePermission.JOB_INTELLIGENCE,)
    assert entry.required_context == (
        "job_search_query",
        "candidate_profile",
        "candidate_evidence",
        "filter_context",
        "policies",
        "source",
    )
    assert entry.preconditions == (
        "phase2_refresh_adapter_available",
        "existing_job_scope",
    )
    for token in ("Phase 1", "discovery", "persistence", "adapter"):
        assert token in entry.description


def test_core_python_entrypoints_resolve_to_declared_methods() -> None:
    for entry in snapshot().entries:
        if entry.kind is not CapabilityKind.CAPABILITY:
            continue
        module_name, object_path = entry.entrypoint.split(":", 1)
        resolved: object = importlib.import_module(module_name)
        for attribute in object_path.split("."):
            resolved = getattr(resolved, attribute)
        assert callable(resolved)


def test_compilation_does_not_import_indexed_entrypoint_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_import(name: str, package: str | None = None) -> object:
        del name, package
        raise AssertionError("registry compilation must not import entrypoints")

    monkeypatch.setattr(importlib, "import_module", fail_import)

    compiled = snapshot()

    assert {entry.id for entry in compiled.entries} == EXPECTED_IDS


def test_policy_paths_exist_inside_the_skill_root() -> None:
    indexed_policy_paths = {
        entry.id: entry.entrypoint
        for entry in snapshot().entries
        if entry.id in EXPECTED_POLICY_PATHS
    }
    assert indexed_policy_paths == EXPECTED_POLICY_PATHS
    resolved_skill_root = SKILL_ROOT.resolve()
    for entry in snapshot().entries:
        if entry.kind is CapabilityKind.POLICY:
            assert entry.input_schema is None
            assert entry.output_schema is None
            resolved_path = (SKILL_ROOT / entry.entrypoint).resolve()
            assert resolved_path.is_relative_to(resolved_skill_root)
            assert resolved_path.is_file()


def test_optimizer_contract_index_names_the_existing_schema_surface() -> None:
    contracts = next(
        entry
        for entry in snapshot().entries
        if entry.id == "repo.optimizer.contracts"
    )
    assert contracts.entrypoint == "references/optimizer/contracts.md"
    text = (SKILL_ROOT / contracts.entrypoint).read_text(encoding="utf-8")
    for contract in (
        "RewriteOperation",
        "ResumeOptimizationPlan",
        "ClaimLedger",
        "VerificationReport",
        "ResumeDiff",
        "ResumeCompatibilityResult",
    ):
        assert contract in text
    assert "Candidate Core" in text
