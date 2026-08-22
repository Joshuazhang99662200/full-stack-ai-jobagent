import builtins
import traceback
from pathlib import Path

import pytest
import yaml

from jobagent.errors import CapabilityRegistryError
from jobagent.optimizer.index import (
    CapabilityIndexLoader,
    CapabilityRegistryCompiler,
)

ENTRY = """
schema_version: "1.0"
entries:
  - id: repo.candidate.detect-gaps
    version: 1.0.0
    kind: capability
    description: Detect evidence gaps before rewriting; output findings only and never edit text.
    entrypoint: jobagent.candidate.gaps:GapDetector.detect
    input_schema: CandidateGapDetectionInput
    output_schema: CandidateGapSet
    intents: [detect_evidence_gap]
    required_context: [candidate_profile, evidence_summary]
    permissions:
      read: [candidate_profile, candidate_evidence]
      write: []
    preconditions: []
    dependencies: []
    produces: [CandidateGap]
    verifiers: []
    failure_policy:
      retry: never
      fallback: return_typed_failure
    trust: core
"""


def test_loader_parses_a_document_inside_root(tmp_path: Path) -> None:
    index = tmp_path / "index.yaml"
    index.write_text(ENTRY, encoding="utf-8")

    document = CapabilityIndexLoader(tmp_path).load(Path("index.yaml"))

    assert document.schema_version == "1.0"
    assert document.entries[0].id == "repo.candidate.detect-gaps"


@pytest.mark.parametrize("path", [Path("../private.yaml"), Path("C:/private.yaml")])
def test_loader_rejects_paths_outside_root_without_echoing_file_body(
    tmp_path: Path,
    path: Path,
) -> None:
    outside = tmp_path.parent / "private.yaml"
    outside.write_text("secret: do-not-echo", encoding="utf-8")

    with pytest.raises(CapabilityRegistryError) as exc_info:
        CapabilityIndexLoader(tmp_path).load(path)

    assert exc_info.value.code == "CAPABILITY_REGISTRY_INVALID"
    assert "do-not-echo" not in str(exc_info.value)


@pytest.mark.parametrize(
    ("body", "secret"),
    [
        ("entries: [secret-yaml", "secret-yaml"),
        (
            ENTRY.replace('schema_version: "1.0"', 'schema_version: "secret-version"'),
            "secret-version",
        ),
        ("- secret-value", "secret-value"),
    ],
)
def test_loader_wraps_yaml_and_contract_failures_without_leaking_input(
    tmp_path: Path,
    body: str,
    secret: str,
) -> None:
    index = tmp_path / "broken.yaml"
    index.write_text(body, encoding="utf-8")

    with pytest.raises(CapabilityRegistryError) as exc_info:
        CapabilityIndexLoader(tmp_path).load(Path("broken.yaml"))

    assert exc_info.value.details == {"path": "broken.yaml"}
    assert str(exc_info.value) == "Capability index document is invalid."
    assert secret not in str(exc_info.value)
    assert secret not in repr(exc_info.value.details)


def test_loader_suppresses_underlying_validation_traceback(tmp_path: Path) -> None:
    index = tmp_path / "secret.yaml"
    index.write_text(
        ENTRY.replace('schema_version: "1.0"', 'schema_version: "secret-version"'),
        encoding="utf-8",
    )

    with pytest.raises(CapabilityRegistryError) as exc_info:
        CapabilityIndexLoader(tmp_path).load(Path("secret.yaml"))

    rendered = "".join(traceback.format_exception(exc_info.value))
    assert "secret-version" not in rendered
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__ is True


def test_loader_wraps_invalid_utf8(tmp_path: Path) -> None:
    index = tmp_path / "invalid.yaml"
    index.write_bytes(b"schema_version: \xff")

    with pytest.raises(CapabilityRegistryError) as exc_info:
        CapabilityIndexLoader(tmp_path).load(Path("invalid.yaml"))

    assert exc_info.value.details == {"path": "invalid.yaml"}
    assert exc_info.value.__cause__ is None


@pytest.mark.parametrize(
    "body",
    [
        "",
        "null\n",
        "scalar-value\n",
    ],
)
def test_loader_rejects_empty_null_and_scalar_documents(
    tmp_path: Path,
    body: str,
) -> None:
    index = tmp_path / "invalid-shape.yaml"
    index.write_text(body, encoding="utf-8")

    with pytest.raises(CapabilityRegistryError) as exc_info:
        CapabilityIndexLoader(tmp_path).load(Path("invalid-shape.yaml"))

    assert str(exc_info.value) == "Capability index document is invalid."
    assert exc_info.value.details == {"path": "invalid-shape.yaml"}


@pytest.mark.parametrize(
    "body",
    [
        ENTRY + "unknown_document_key: forbidden\n",
        ENTRY.replace(
            "    trust: core\n",
            "    trust: core\n    unknown_entry_key: forbidden\n",
        ),
    ],
)
def test_loader_rejects_unknown_yaml_keys(tmp_path: Path, body: str) -> None:
    index = tmp_path / "unknown-key.yaml"
    index.write_text(body, encoding="utf-8")

    with pytest.raises(CapabilityRegistryError) as exc_info:
        CapabilityIndexLoader(tmp_path).load(Path("unknown-key.yaml"))

    assert str(exc_info.value) == "Capability index document is invalid."
    assert exc_info.value.details == {"path": "unknown-key.yaml"}
    assert "forbidden" not in str(exc_info.value)


def test_loader_safe_load_rejects_python_object_tags_without_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []

    def record_print(*args: object, **kwargs: object) -> None:
        del kwargs
        calls.append(args)

    monkeypatch.setattr(builtins, "print", record_print)
    index = tmp_path / "object-tag.yaml"
    index.write_text(
        "!!python/object/apply:builtins.print ['must-not-run']\n",
        encoding="utf-8",
    )

    with pytest.raises(CapabilityRegistryError) as exc_info:
        CapabilityIndexLoader(tmp_path).load(Path("object-tag.yaml"))

    assert str(exc_info.value) == "Capability index document is invalid."
    assert exc_info.value.details == {"path": "object-tag.yaml"}
    assert exc_info.value.__cause__ is None
    assert calls == []


def test_loader_rejects_duplicate_mapping_keys(tmp_path: Path) -> None:
    index = tmp_path / "duplicate-key.yaml"
    index.write_text(
        ENTRY.replace(
            "    permissions:\n      read:",
            "    permissions:\n      write: []\n      write: [canonical_evidence]\n      read:",
        ),
        encoding="utf-8",
    )

    with pytest.raises(CapabilityRegistryError) as exc_info:
        CapabilityIndexLoader(tmp_path).load(Path("duplicate-key.yaml"))

    assert str(exc_info.value) == "Capability index document is invalid."
    assert exc_info.value.details == {"path": "duplicate-key.yaml"}
    assert "canonical_evidence" not in str(exc_info.value)


def test_loader_wraps_path_resolution_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_resolve = Path.resolve

    def fail_for_loop(path: Path, strict: bool = False) -> Path:
        if path.name == "loop.yaml":
            raise RuntimeError("secret symlink target")
        return original_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", fail_for_loop)

    with pytest.raises(CapabilityRegistryError) as exc_info:
        CapabilityIndexLoader(tmp_path).load(Path("loop.yaml"))

    assert exc_info.value.details == {"path": "loop.yaml"}
    rendered = "".join(traceback.format_exception(exc_info.value))
    assert "secret symlink target" not in rendered


def test_loader_wraps_root_resolution_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_resolution(path: Path, strict: bool = False) -> Path:
        del path, strict
        raise RuntimeError("secret registry root")

    monkeypatch.setattr(Path, "resolve", fail_resolution)

    with pytest.raises(CapabilityRegistryError) as exc_info:
        CapabilityIndexLoader(tmp_path)

    assert str(exc_info.value) == "Capability index root is invalid."
    assert exc_info.value.details == {}
    rendered = "".join(traceback.format_exception(exc_info.value))
    assert "secret registry root" not in rendered


def test_compiler_sorts_entries_and_has_a_stable_digest(tmp_path: Path) -> None:
    first = tmp_path / "first.yaml"
    second = tmp_path / "second.yaml"
    first.write_text(ENTRY, encoding="utf-8")
    second.write_text(
        ENTRY.replace("repo.candidate.detect-gaps", "repo.candidate.ask-question")
        .replace("detect_evidence_gap", "ask_evidence_question"),
        encoding="utf-8",
    )
    compiler = CapabilityRegistryCompiler(CapabilityIndexLoader(tmp_path))

    left = compiler.compile([Path("first.yaml"), Path("second.yaml")])
    right = compiler.compile([Path("second.yaml"), Path("first.yaml")])

    assert [entry.id for entry in left.entries] == [
        "repo.candidate.ask-question",
        "repo.candidate.detect-gaps",
    ]
    assert left.digest == right.digest
    assert left.digest.startswith("sha256:")
    assert len(left.digest) == len("sha256:") + 64


def test_compiler_digest_ignores_yaml_mapping_key_order(tmp_path: Path) -> None:
    canonical = tmp_path / "canonical.yaml"
    reordered = tmp_path / "reordered.yaml"
    canonical.write_text(ENTRY, encoding="utf-8")
    payload = yaml.safe_load(ENTRY)
    assert isinstance(payload, dict)
    entry = payload["entries"][0]
    payload["entries"][0] = dict(reversed(entry.items()))
    reordered.write_text(
        yaml.safe_dump(dict(reversed(payload.items())), sort_keys=False),
        encoding="utf-8",
    )
    compiler = CapabilityRegistryCompiler(CapabilityIndexLoader(tmp_path))

    left = compiler.compile([Path("canonical.yaml")])
    right = compiler.compile([Path("reordered.yaml")])

    assert left.digest == right.digest


def test_compiler_digest_changes_when_semantic_metadata_changes(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.yaml"
    changed = tmp_path / "changed.yaml"
    baseline.write_text(ENTRY, encoding="utf-8")
    changed.write_text(
        ENTRY.replace("detect_evidence_gap", "detect_candidate_evidence_gap"),
        encoding="utf-8",
    )
    compiler = CapabilityRegistryCompiler(CapabilityIndexLoader(tmp_path))

    left = compiler.compile([Path("baseline.yaml")])
    right = compiler.compile([Path("changed.yaml")])

    assert left.digest != right.digest


def test_compiler_rejects_an_empty_document_set(tmp_path: Path) -> None:
    compiler = CapabilityRegistryCompiler(CapabilityIndexLoader(tmp_path))

    with pytest.raises(CapabilityRegistryError) as exc_info:
        compiler.compile([])

    assert str(exc_info.value) == "Capability registry requires at least one document."
    assert exc_info.value.details == {}


def test_compiler_rejects_duplicate_capability_ids(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.yaml"
    duplicate.write_text(ENTRY, encoding="utf-8")

    with pytest.raises(CapabilityRegistryError) as exc_info:
        CapabilityRegistryCompiler(CapabilityIndexLoader(tmp_path)).compile(
            [Path("duplicate.yaml"), Path("duplicate.yaml")]
        )

    assert "duplicate capability id" in str(exc_info.value)
    assert exc_info.value.details == {
        "capability_id": "repo.candidate.detect-gaps"
    }


@pytest.mark.parametrize("reference_field", ["dependencies", "verifiers"])
def test_compiler_rejects_unknown_registry_references(
    tmp_path: Path,
    reference_field: str,
) -> None:
    missing = tmp_path / "missing.yaml"
    missing.write_text(
        ENTRY.replace(f"{reference_field}: []", f"{reference_field}: [repo.missing.entry]"),
        encoding="utf-8",
    )

    with pytest.raises(CapabilityRegistryError) as exc_info:
        CapabilityRegistryCompiler(CapabilityIndexLoader(tmp_path)).compile(
            [Path("missing.yaml")]
        )

    assert "unknown registry reference" in str(exc_info.value)
    assert exc_info.value.details == {
        "capability_id": "repo.candidate.detect-gaps",
        "reference_id": "repo.missing.entry",
    }
