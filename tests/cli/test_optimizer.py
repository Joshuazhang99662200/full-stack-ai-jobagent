import json
import tomllib
from pathlib import Path

import pytest
import typer
from typer.core import TyperGroup
from typer.testing import CliRunner

from jobagent import skill_resources
from jobagent.cli import optimizer as optimizer_cli
from jobagent.cli.app import app
from jobagent.errors import CapabilityRegistryError

runner = CliRunner()


def invoke(*args: str) -> tuple[int, object]:
    result = runner.invoke(app, list(args))
    payload = json.loads(result.stdout) if result.stdout else None
    return result.exit_code, payload


def test_optimizer_exposes_tailoring_but_never_delivery() -> None:
    root_command = typer.main.get_command(app)
    assert isinstance(root_command, TyperGroup)
    optimizer_command = root_command.commands["optimizer"]

    assert isinstance(optimizer_command, TyperGroup)
    assert set(optimizer_command.commands) == {"capabilities", "tailor", "assemble"}
    # Tailoring is in scope; approval and delivery never are.
    for forbidden in (
        "run",
        "rewrite",
        "apply",
        "approve",
        "send",
        "deliver",
        "browser",
    ):
        result = runner.invoke(app, ["optimizer", forbidden])
        assert result.exit_code == 2


def test_capabilities_emits_deterministic_snapshot_json() -> None:
    exit_code, payload = invoke("optimizer", "capabilities")

    assert exit_code == 0
    assert isinstance(payload, dict)
    assert set(payload) == {"schema_version", "digest", "entries"}
    assert payload["schema_version"] == "1.0"
    assert payload["digest"].startswith("sha256:")
    ids = [entry["id"] for entry in payload["entries"]]
    assert len(ids) == 18
    assert ids == sorted(ids)
    assert "repo.candidate.detect-gaps" in ids


def test_capabilities_filters_by_kind_and_intent_without_forging_digest() -> None:
    full_code, snapshot = invoke("optimizer", "capabilities")
    kind_code, policies = invoke("optimizer", "capabilities", "--kind", "policy")
    intent_code, matching = invoke(
        "optimizer", "capabilities", "--intent", "detect_candidate_evidence_gaps"
    )

    assert full_code == kind_code == intent_code == 0
    assert isinstance(snapshot, dict)
    assert isinstance(policies, dict)
    assert set(policies) == {"schema_version", "source_digest", "entries"}
    assert policies["schema_version"] == "1.0"
    assert policies["source_digest"] == snapshot["digest"]
    assert "digest" not in policies
    assert len(policies["entries"]) == 10
    assert [entry["id"] for entry in policies["entries"]] == sorted(
        entry["id"] for entry in policies["entries"]
    )
    assert all(entry["kind"] == "policy" for entry in policies["entries"])
    assert isinstance(matching, dict)
    assert set(matching) == {"schema_version", "source_digest", "entries"}
    assert matching["source_digest"] == snapshot["digest"]
    assert [entry["id"] for entry in matching["entries"]] == [
        "repo.candidate.detect-gaps"
    ]


def test_unknown_filter_returns_an_empty_filtered_snapshot() -> None:
    exit_code, payload = invoke("optimizer", "capabilities", "--intent", "missing_intent")

    assert exit_code == 0
    assert isinstance(payload, dict)
    assert set(payload) == {"schema_version", "source_digest", "entries"}
    assert payload["schema_version"] == "1.0"
    assert payload["entries"] == []
    assert payload["source_digest"].startswith("sha256:")
    assert "digest" not in payload


def test_default_skill_root_is_independent_of_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    exit_code, payload = invoke("optimizer", "capabilities")

    assert exit_code == 0
    assert isinstance(payload, dict)
    assert len(payload["entries"]) == 18


def test_packaged_skill_root_has_priority(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    package_root = tmp_path / "jobagent" / "optimizer"
    bundled_root = package_root / "resources" / "job-hunting"
    bundled_root.mkdir(parents=True)
    # Resolution lives in jobagent.skill_resources; the CLI delegates to it.
    monkeypatch.setattr(skill_resources.resources, "files", lambda package: package_root)

    assert optimizer_cli._default_skill_root() == bundled_root


def test_wheel_maps_the_single_authoritative_skill_tree() -> None:
    pyproject_path = Path(__file__).parents[2] / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    assert pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"] == {
        "skills/job-hunting": "jobagent/optimizer/resources/job-hunting"
    }


@pytest.mark.parametrize("intent", ["", "   ", "\t"])
def test_blank_intent_returns_a_structured_input_error_without_echoing_input(
    intent: str,
) -> None:
    result = runner.invoke(app, ["optimizer", "capabilities", "--intent", intent])

    assert result.exit_code == 1
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload == {
        "error": {
            "code": "CONTRACT_VALIDATION_ERROR",
            "message": "Capability intent filter is invalid.",
            "details": {"field": "intent"},
        }
    }
    if intent:
        assert intent not in json.dumps(payload)


def test_intent_matching_is_case_sensitive() -> None:
    exit_code, payload = invoke(
        "optimizer", "capabilities", "--intent", "DETECT_CANDIDATE_EVIDENCE_GAPS"
    )

    assert exit_code == 0
    assert isinstance(payload, dict)
    assert payload["entries"] == []


def test_intent_filter_strips_surrounding_whitespace_before_matching() -> None:
    exit_code, payload = invoke(
        "optimizer",
        "capabilities",
        "--intent",
        "  detect_candidate_evidence_gaps\t",
    )

    assert exit_code == 0
    assert isinstance(payload, dict)
    assert [entry["id"] for entry in payload["entries"]] == [
        "repo.candidate.detect-gaps"
    ]


def test_kind_filter_is_case_insensitive_and_invalid_kind_is_a_click_error() -> None:
    policy_result = runner.invoke(app, ["optimizer", "capabilities", "--kind", "POLICY"])
    invalid_result = runner.invoke(app, ["optimizer", "capabilities", "--kind", "invalid"])

    assert policy_result.exit_code == 0
    assert all(entry["kind"] == "policy" for entry in json.loads(policy_result.stdout)["entries"])
    assert invalid_result.exit_code == 2
    assert invalid_result.stdout == ""
    assert "Invalid value" in invalid_result.stderr


def test_registry_failure_is_structured_stdout_json_with_empty_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail() -> object:
        raise CapabilityRegistryError(
            "Capability index document is invalid.",
            details={"path": "optimizer/index/repository.yaml"},
        )

    monkeypatch.setattr(optimizer_cli, "_snapshot_provider", fail)

    result = runner.invoke(app, ["optimizer", "capabilities"])

    assert result.exit_code == 1
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "CAPABILITY_REGISTRY_INVALID"
    assert payload["error"]["details"] == {"path": "optimizer/index/repository.yaml"}
    assert set(payload["error"]) == {"code", "message", "details"}
