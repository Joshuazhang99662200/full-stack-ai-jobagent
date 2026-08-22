import json
from pathlib import Path

from typer.testing import CliRunner

from jobagent.cli.app import app

runner = CliRunner()


def invoke(*args: str) -> tuple[int, object]:
    result = runner.invoke(app, list(args))
    payload = json.loads(result.stdout) if result.stdout else None
    return result.exit_code, payload


def test_optimizer_help_exposes_discovery_only() -> None:
    result = runner.invoke(app, ["optimizer", "--help"])

    assert result.exit_code == 0
    assert "capabilities" in result.stdout
    for forbidden in (
        "run",
        "rewrite",
        "apply",
        "approve",
        "send",
        "deliver",
        "browser",
    ):
        assert forbidden not in result.stdout.casefold()


def test_capabilities_emits_deterministic_snapshot_json() -> None:
    exit_code, payload = invoke("optimizer", "capabilities")

    assert exit_code == 0
    assert isinstance(payload, dict)
    assert payload["schema_version"] == "1.0"
    assert payload["digest"].startswith("sha256:")
    ids = [entry["id"] for entry in payload["entries"]]
    assert len(ids) == 14
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
    assert policies["schema_version"] == "1.0"
    assert policies["source_digest"] == snapshot["digest"]
    assert "digest" not in policies
    assert len(policies["entries"]) == 6
    assert all(entry["kind"] == "policy" for entry in policies["entries"])
    assert isinstance(matching, dict)
    assert matching["source_digest"] == snapshot["digest"]
    assert [entry["id"] for entry in matching["entries"]] == [
        "repo.candidate.detect-gaps"
    ]


def test_unknown_filter_returns_an_empty_filtered_snapshot() -> None:
    exit_code, payload = invoke("optimizer", "capabilities", "--intent", "missing_intent")

    assert exit_code == 0
    assert isinstance(payload, dict)
    assert payload["schema_version"] == "1.0"
    assert payload["entries"] == []
    assert payload["source_digest"].startswith("sha256:")
    assert "digest" not in payload


def test_default_skill_root_is_independent_of_working_directory(
    tmp_path: Path, monkeypatch: object
) -> None:
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]

    exit_code, payload = invoke("optimizer", "capabilities")

    assert exit_code == 0
    assert isinstance(payload, dict)
    assert len(payload["entries"]) == 14


def test_registry_failure_is_structured_and_does_not_echo_yaml(
    tmp_path: Path, monkeypatch: object
) -> None:
    index_root = tmp_path / "job-hunting"
    index_directory = index_root / "optimizer" / "index"
    index_directory.mkdir(parents=True)
    private_body = "secret: do-not-echo"
    (index_directory / "repository.yaml").write_text(private_body, encoding="utf-8")
    (index_directory / "policies.yaml").write_text(private_body, encoding="utf-8")
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "jobagent.cli.optimizer.DEFAULT_SKILL_ROOT", index_root
    )

    exit_code, payload = invoke("optimizer", "capabilities")

    assert exit_code == 1
    assert isinstance(payload, dict)
    assert payload["error"]["code"] == "CAPABILITY_REGISTRY_INVALID"
    assert payload["error"]["details"] == {"path": "optimizer/index/repository.yaml"}
    assert "do-not-echo" not in json.dumps(payload)
