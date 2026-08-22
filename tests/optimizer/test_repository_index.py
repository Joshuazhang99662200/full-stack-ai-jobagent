from importlib.util import find_spec
from pathlib import Path

import yaml

from jobagent.optimizer.index import CapabilityIndexLoader, CapabilityRegistryCompiler
from jobagent.schemas.optimizer_registry import (
    CapabilityKind,
    CapabilityRegistrySnapshot,
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
    "approve",
    "send",
    "deliver",
    "connector",
    "captcha",
    "login",
    "browser",
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
    assert writers[0].preconditions == ("explicit_user_confirmation",)


def test_python_entrypoint_modules_exist_without_importing_them() -> None:
    modules = {
        entry.entrypoint.split(":", 1)[0]
        for entry in snapshot().entries
        if entry.kind is CapabilityKind.CAPABILITY
    }
    assert all(find_spec(module) is not None for module in modules)


def test_policy_paths_exist_inside_the_skill_root() -> None:
    for entry in snapshot().entries:
        if entry.kind is CapabilityKind.POLICY:
            assert entry.input_schema is None
            assert entry.output_schema is None
            assert (SKILL_ROOT / entry.entrypoint).is_file()
