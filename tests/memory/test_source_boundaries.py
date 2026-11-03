"""Adversarial synthetic checks for source/snapshot identity and private paths."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from jobagent.bridge.preference_memory import MarkdownPreferenceStore
from jobagent.cli.app import app
from jobagent.schemas.preference_memory import PreferenceMemory, PreferenceRule


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "candidate/private/memory-check"
    root.mkdir(parents=True)
    config = root / "config.json"
    store = root / "snapshots.sqlite3"
    preference = root / "preferences.md"
    config.write_text(
        json.dumps(
            {
                "candidate_id": "CAND_TEST",
                "private_root": str(root),
                "sources": [
                    {
                        "source_id": "writing",
                        "kind": "preference_memory",
                        "candidate_id": "CAND_TEST",
                        "path": str(preference),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return root, config, store, preference


def call(config, store, command, *args):
    return CliRunner().invoke(
        app, ["memory", command, "--config", str(config), "--store", str(store), *args]
    )


def write_preference(path, version, text, previous="PMEM_EMPTY"):
    memory = PreferenceMemory(
        candidate_id="CAND_TEST",
        version=version,
        consumed_event_ids=["EVENT_ONE"],
        rules=[
            PreferenceRule(
                rule_id="WRITING_ONE",
                category="greetings",
                scope="general",
                condition="Always",
                text=text,
                source_event_ids=["EVENT_ONE"],
                updated_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        ],
    )
    MarkdownPreferenceStore(path, "CAND_TEST").save(memory, expected_version=previous)


def compile_snapshot(config, store):
    result = call(config, store, "compile")
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_snapshot_metadata_tampering_cannot_rebind_an_old_id(workspace):
    _, config, store, preference = workspace
    write_preference(preference, "PMEM_ONE", "Keep it brief.")
    first = compile_snapshot(config, store)
    write_preference(preference, "PMEM_TWO", "Keep details.", previous="PMEM_ONE")
    second = compile_snapshot(config, store)
    modified = {**first, "sources": second["sources"]}
    with sqlite3.connect(store) as connection:
        connection.execute(
            "UPDATE memory_snapshots SET snapshot_json=? WHERE snapshot_id=?",
            (json.dumps(modified), first["snapshot_id"]),
        )
    result = call(
        config, store, "context", "--snapshot", first["snapshot_id"], "--task", "greeting"
    )
    assert result.exit_code == 1 or json.loads(result.output)["usable"] is False
    assert "Keep details." not in result.output


def test_preference_context_and_digest_come_from_same_captured_content(workspace, monkeypatch):
    _, config, store, preference = workspace
    write_preference(preference, "PMEM_ONE", "Captured version one.")
    original = preference.read_bytes()
    write_preference(preference, "PMEM_TWO", "Different read version.", previous="PMEM_ONE")
    changed = preference.read_text(encoding="utf-8")
    preference.write_bytes(original)
    actual_read_text = Path.read_text

    def mismatched_read(path, *args, **kwargs):
        if path.resolve() == preference.resolve():
            return changed
        return actual_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", mismatched_read)
    snapshot = compile_snapshot(config, store)
    result = call(
        config, store, "context", "--snapshot", snapshot["snapshot_id"], "--task", "greeting"
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert "Different read version." not in result.output
    assert not data["usable"] or data["items"][0]["text"] == "Captured version one."


def test_private_symlink_cannot_expose_an_outside_source(workspace, tmp_path):
    root, config, store, preference = workspace
    public = tmp_path / "public.md"
    public.write_text("outside-private-source", encoding="utf-8")
    try:
        preference.symlink_to(public)
    except OSError:
        pytest.skip("Symlink creation is unavailable on this system.")
    result = call(config, store, "compile")
    assert result.exit_code == 1, result.output
    assert "outside-private-source" not in result.output
    assert not store.exists() and root.exists()


def test_source_disappearance_blocks_context_without_recreating_the_file(workspace):
    _, config, store, preference = workspace
    write_preference(preference, "PMEM_ONE", "Keep it brief.")
    snapshot = compile_snapshot(config, store)
    preference.unlink()
    result = call(
        config, store, "context", "--snapshot", snapshot["snapshot_id"], "--task", "greeting"
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["usable"] is False and data["items"] == []
    assert not preference.exists()


@pytest.mark.parametrize("invalid_json", ["null", "[]", '"not-an-event-object"'])
def test_nonobject_json_in_rule_chain_is_an_invalid_source(workspace, invalid_json):
    from jobagent.schemas.candidate import CandidateProfile
    from jobagent.storage.candidate_repository import SqliteCandidateRepository
    from tests.storage.test_message_diff import repository

    root, config, store, _ = workspace
    repo = repository(root)
    SqliteCandidateRepository(repo.database).save_profile(CandidateProfile(id="CAND_DEMO"))
    with repo.database.connect() as connection, connection:
        connection.execute(
            "INSERT INTO message_diff_events VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "BAD_EVENT",
                "CAND_DEMO",
                "JOB_DEMO_1",
                "BAD_DRAFT",
                "sha256:synthetic-invalid",
                invalid_json,
                "{}",
            ),
        )
    config.write_text(
        json.dumps(
            {
                "candidate_id": "CAND_DEMO",
                "private_root": str(root),
                "sources": [
                    {
                        "source_id": "rules",
                        "kind": "confirmed_rules",
                        "candidate_id": "CAND_DEMO",
                        "path": str(repo.database.path),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    result = call(config, store, "status")
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["sources"][0]["state"] == "invalid"
    assert not store.exists()
