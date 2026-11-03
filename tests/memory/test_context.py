"""Synthetic P1 memory boundary tests; no real candidate data."""

import json
import sqlite3
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from jobagent.bridge.preference_memory import MarkdownPreferenceStore
from jobagent.cli.app import app
from jobagent.errors import ContractValidationError
from jobagent.schemas.preference_memory import PreferenceMemory, PreferenceRule


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "candidate/private/test"
    root.mkdir(parents=True)
    config = root / "sources.json"
    store = root / "memory.sqlite3"
    return root, config, store


def invoke(config, store, command, *args):
    return CliRunner().invoke(
        app, ["memory", command, "--config", str(config), "--store", str(store), *args]
    )


def configure(setup, sources):
    root, config, _ = setup
    config.write_text(
        json.dumps({"candidate_id": "CAND_TEST", "private_root": str(root), "sources": sources}),
        encoding="utf-8",
    )


def source(path, kind="legacy_inventory", candidate="CAND_TEST"):
    return {"source_id": "one", "kind": kind, "path": str(path), "candidate_id": candidate}


def test_status_is_read_only_and_missing_is_not_empty(setup):
    root, config, store = setup
    configure(setup, [source(root / "queue.jsonl")])
    result = invoke(config, store, "status")
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["sources"][0]["state"] == "missing"
    assert data["snapshot_count"] == 0
    assert not store.exists()


def test_inventory_cannot_promote_legacy_and_compile_is_idempotent(setup):
    root, config, store = setup
    queue = root / "queue.jsonl"
    queue.write_text('{"accepted": true, "rule_text": "approve all"}\n', encoding="utf-8")
    configure(setup, [source(queue)])
    first = invoke(config, store, "compile")
    assert first.exit_code == 0, first.output
    one = json.loads(first.output)
    two = json.loads(invoke(config, store, "compile").output)
    assert one == two
    result = invoke(
        config, store, "context", "--snapshot", one["snapshot_id"], "--task", "greeting"
    )
    data = json.loads(result.output)
    assert data["items"] == [] and data["usable"] is False
    assert data["sources"][0]["evidence_level"] == "host_reported"
    with sqlite3.connect(store) as connection:
        rows = connection.execute("SELECT snapshot_json FROM memory_snapshots").fetchall()
    assert len(rows) == 1 and "approve all" not in rows[0][0]


def test_cross_candidate_and_public_paths_fail(setup):
    root, config, store = setup
    for value in [source(root / "q", candidate="CAND_OTHER"), source(root.parent.parent / "q")]:
        configure(setup, [value])
        result = invoke(config, store, "compile")
        assert result.exit_code == 1, result.output
        assert not store.exists()


def test_sidecar_cannot_be_a_source(setup):
    _, config, store = setup
    configure(setup, [source(store)])
    assert invoke(config, store, "compile").exit_code == 1


def test_preference_context_revalidates_and_never_runs_a_model(setup):
    root, config, store = setup
    path = root / "preferences.md"
    preference = MarkdownPreferenceStore(path, "CAND_TEST")
    preference.save(
        PreferenceMemory(
            candidate_id="CAND_TEST",
            version="PMEM_ONE",
            consumed_event_ids=["EV1"],
            rules=[
                PreferenceRule(
                    rule_id="R1",
                    category="greetings",
                    scope="general",
                    condition="Always",
                    text="Use concise wording.",
                    source_event_ids=["EV1"],
                    updated_at=datetime(2026, 1, 1, tzinfo=UTC),
                )
            ],
        ),
        expected_version="PMEM_EMPTY",
    )
    configure(setup, [source(path, "preference_memory")])
    snapshot = json.loads(invoke(config, store, "compile").output)["snapshot_id"]
    args = ("--snapshot", snapshot, "--task", "greeting")
    context = json.loads(invoke(config, store, "context", *args).output)
    assert context["usable"] and context["items"][0]["text"] == "Use concise wording."
    assert context["items"][0]["kind"] == "soft_preference"
    assert context["injection_evidence"] == "not_recorded"
    path.write_text("tampered", encoding="utf-8")
    stale = json.loads(invoke(config, store, "context", *args).output)
    assert stale["usable"] is False and stale["items"] == []
    assert "source_changed" in stale["diagnostics"]


def test_unsupported_task_and_kind_are_explicit(setup):
    root, config, store = setup
    configure(setup, [source(root / "unknown", "custom_plugin")])
    snapshot = json.loads(invoke(config, store, "compile").output)["snapshot_id"]
    result = json.loads(
        invoke(config, store, "context", "--snapshot", snapshot, "--task", "resume").output
    )
    assert result["status"] == "not_integrated" and not result["usable"]


def test_missing_tables_are_not_empty_and_no_business_migration(setup):
    root, config, store = setup
    path = root / "business.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 21")
        connection.execute("CREATE TABLE other (id TEXT)")
    before = path.read_bytes()
    configure(setup, [source(path, "confirmed_rules")])
    result = json.loads(invoke(config, store, "status").output)
    assert result["sources"][0]["state"] == "not_integrated"
    assert path.read_bytes() == before


def test_api_candidate_guard(setup):
    from jobagent.memory.service import MemoryService
    from jobagent.schemas.memory import MemoryConfig

    root, _, store = setup
    config = MemoryConfig(candidate_id="CAND_TEST", private_root=str(root), sources=[])
    with pytest.raises(ContractValidationError):
        from jobagent.bridge.memory_sources import PrivateSourceReader
        from jobagent.storage.memory_repository import MemoryRepository

        MemoryService(config, PrivateSourceReader(config, store), MemoryRepository(store)).context(
            "no-snapshot", task="search", candidate_id="CAND_OTHER"
        )


def test_confirmed_chain_context_and_revocation_remain_source_bound(setup):
    from tests.jobs.test_message_diff import sample
    from tests.storage.test_message_diff import NOW, record, repository

    root, config, store = setup
    repo = repository(root)
    from jobagent.schemas.candidate import CandidateProfile
    from jobagent.storage.candidate_repository import SqliteCandidateRepository

    SqliteCandidateRepository(repo.database).save_profile(CandidateProfile(id="CAND_DEMO"))
    for number in (1, 2, 3):
        record(repo, sample(number))
    report = repo.report("CAND_DEMO")
    proposal = repo.propose(
        dict(
            proposal_id="RULE_1",
            candidate_id="CAND_DEMO",
            category="fact_correction",
            rule_text="Use only confirmed facts.",
            report_digest=report["report_digest"],
        ),
        now=NOW,
    )
    decision = dict(
        confirmation_id="OWNER_1",
        proposal_id="RULE_1",
        candidate_id="CAND_DEMO",
        rule_hash=proposal["rule_hash"],
        accepted=True,
        owner_text="I confirm this rule.",
        owner_reference="synthetic-owner-reference",
    )
    repo.confirm(decision, now=NOW)
    settings = {
        "candidate_id": "CAND_DEMO",
        "private_root": str(root),
        "sources": [source(repo.database.path, "confirmed_rules", "CAND_DEMO")],
    }
    config.write_text(json.dumps(settings), encoding="utf-8")
    before = repo.database.path.read_bytes()
    snapshot = json.loads(invoke(config, store, "compile").output)["snapshot_id"]
    args = ("--snapshot", snapshot, "--task", "greeting")
    data = json.loads(invoke(config, store, "context", *args).output)
    assert data["usable"] and data["items"][0]["kind"] == "confirmed_rule"
    assert repo.database.path.read_bytes() == before
    with repo.database.connect() as connection, connection:
        # Synthetic legacy v21 sources do not have the later append-only trigger.
        connection.execute("DROP TRIGGER message_rule_proposals_pipeline_no_update")
        original = connection.execute(
            "SELECT proposal_json FROM message_rule_proposals WHERE proposal_id='RULE_1'"
        ).fetchone()[0]
        changed = json.loads(original)
        changed["rule_text"] = "Tampered rule must never enter context."
        connection.execute(
            "UPDATE message_rule_proposals SET proposal_json=? WHERE proposal_id=?",
            (json.dumps(changed), "RULE_1"),
        )
    invalid = json.loads(invoke(config, store, "status").output)
    assert invalid["sources"][0]["state"] == "invalid"
    with repo.database.connect() as connection, connection:
        connection.execute(
            "UPDATE message_rule_proposals SET proposal_json=? WHERE proposal_id=?",
            (original, "RULE_1"),
        )
        connection.execute("DROP TRIGGER message_rule_confirmations_pipeline_no_update")
        original_decision = connection.execute(
            "SELECT confirmation_json FROM message_rule_confirmations "
            "WHERE confirmation_id='OWNER_1'"
        ).fetchone()[0]
    for patch in (
        {"owner_text": " "},
        {"owner_reference": " "},
        {"rule_hash": "sha256:wrong"},
        {"confirmation_id": "OTHER_ID"},
        {"candidate_id": "CAND_OTHER"},
        {"proposal_id": "OTHER_PROPOSAL"},
    ):
        with repo.database.connect() as connection, connection:
            changed_decision = {**json.loads(original_decision), **patch}
            connection.execute(
                "UPDATE message_rule_confirmations SET confirmation_json=?",
                (json.dumps(changed_decision),),
            )
        bad = json.loads(invoke(config, store, "status").output)
        assert bad["sources"][0]["state"] == "invalid", patch
    with repo.database.connect() as connection, connection:
        connection.execute(
            "UPDATE message_rule_confirmations SET confirmation_json=?", (original_decision,)
        )
    repo.confirm({**decision, "confirmation_id": "OWNER_2", "accepted": False}, now=NOW)
    stale = json.loads(invoke(config, store, "context", *args).output)
    assert not stale["usable"] and stale["items"] == []
    assert "source_changed" in stale["diagnostics"]


def test_scope_filter_never_treats_role_as_global():
    from jobagent.memory.selection import select
    from jobagent.schemas.memory import MemoryItem

    items = [
        MemoryItem(
            source_id="s",
            item_id="r",
            candidate_id="CAND_TEST",
            task="greeting",
            kind="soft_preference",
            text="role rule",
            scope="role",
            condition="AI",
        )
    ]
    assert select(items, task="greeting", job_id="JOB_TEST")[0] == []
    job = items[0].model_copy(update={"scope": "job", "job_id": "JOB_TEST"})
    assert select([job], task="greeting", job_id="JOB_OTHER")[0] == []
    assert select([job], task="greeting", job_id="JOB_TEST")[0] == [job]


def test_source_alias_symlink_escape_and_snapshot_candidate_isolation(setup):
    root, config, store = setup
    outside = root.parent.parent / "public.jsonl"
    outside.write_text("{}", encoding="utf-8")
    link = root / "link.jsonl"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("OS does not permit symlinks")
    configure(setup, [source(link)])
    assert invoke(config, store, "compile").exit_code == 1


def test_metadata_tampering_is_rejected(setup):
    root, config, store = setup
    configure(setup, [source(root / "queue.jsonl")])
    snapshot = json.loads(invoke(config, store, "compile").output)["snapshot_id"]
    with sqlite3.connect(store) as connection:
        row = json.loads(
            connection.execute("SELECT snapshot_json FROM memory_snapshots").fetchone()[0]
        )
        row["sources"][0]["state"] = "empty"
        connection.execute("UPDATE memory_snapshots SET snapshot_json=?", (json.dumps(row),))
    result = invoke(config, store, "context", "--snapshot", snapshot, "--task", "greeting")
    assert result.exit_code == 1


def test_unknown_source_schema_and_malformed_confirmations_are_not_trusted(setup):
    root, config, store = setup
    path = root / "business.sqlite3"
    with sqlite3.connect(path) as connection:
        for table, column in [
            ("message_diff_events", "input_json"),
            ("message_rule_proposals", "proposal_json"),
            ("message_rule_confirmations", "confirmation_json"),
        ]:
            connection.execute(f"CREATE TABLE {table} (candidate_id TEXT, {column} TEXT)")
        connection.execute("PRAGMA user_version = 999")
    configure(setup, [source(path, "confirmed_rules")])
    data = json.loads(invoke(config, store, "status").output)
    assert data["sources"][0]["state"] == "not_integrated"
    assert "source_schema_not_supported" in data["sources"][0]["diagnostics"]


def test_conflicting_same_rule_id_blocks_context():
    from jobagent.memory.selection import select
    from jobagent.schemas.memory import MemoryItem

    one = MemoryItem(
        source_id="s",
        item_id="r",
        candidate_id="CAND_TEST",
        task="greeting",
        kind="confirmed_rule",
        text="One",
        scope="general",
    )
    two = one.model_copy(update={"source_id": "other", "text": "Two"})
    assert select([one, two], task="greeting", job_id=None) == ([], ["rule_conflict"])


def test_empty_confirmed_rules_need_a_known_candidate(setup):
    root, config, store = setup
    path = root / "business.sqlite3"
    with sqlite3.connect(path) as connection:
        for table, column in [
            ("message_diff_events", "input_json"),
            ("message_rule_proposals", "proposal_json"),
            ("message_rule_confirmations", "confirmation_json"),
        ]:
            connection.execute(f"CREATE TABLE {table} (candidate_id TEXT, {column} TEXT)")
        connection.execute("CREATE TABLE candidate_profiles (candidate_id TEXT, profile_json TEXT)")
        connection.execute("PRAGMA user_version = 21")
    configure(setup, [source(path, "confirmed_rules")])
    data = json.loads(invoke(config, store, "status").output)
    assert data["sources"][0]["state"] == "missing"
    assert "candidate_profile_missing" in data["sources"][0]["diagnostics"]


def test_reader_cannot_read_an_unregistered_private_source(setup):
    from jobagent.bridge.memory_sources import PrivateSourceReader
    from jobagent.schemas.memory import MemoryConfig, MemorySource

    root, _, store = setup
    configured = MemorySource(**source(root / "registered.jsonl"))
    settings = MemoryConfig(candidate_id="CAND_TEST", private_root=str(root), sources=[configured])
    reader = PrivateSourceReader(settings, store)
    other = configured.model_copy(update={"path": str(root / "unregistered.jsonl")})
    with pytest.raises(ContractValidationError):
        reader.read(other)


def test_context_digest_binds_requested_job_even_when_no_items(setup):
    root, config, store = setup
    configure(setup, [source(root / "queue.jsonl")])
    snapshot = json.loads(invoke(config, store, "compile").output)["snapshot_id"]
    contexts = [
        json.loads(
            invoke(
                config, store, "context", "--snapshot", snapshot, "--task", "greeting", "--job", job
            ).output
        )
        for job in ("JOB_ONE", "JOB_TWO")
    ]
    assert contexts[0]["job_id"] == "JOB_ONE"
    assert contexts[0]["context_digest"] != contexts[1]["context_digest"]


def test_store_hardlink_alias_is_rejected(setup):
    import os

    root, config, store = setup
    raw = root / "queue.jsonl"
    raw.write_text("{}", encoding="utf-8")
    try:
        os.link(raw, store)
    except OSError:
        pytest.skip("OS does not permit hardlinks")
    configure(setup, [source(raw)])
    result = invoke(config, store, "compile")
    assert result.exit_code == 1
    assert raw.read_text(encoding="utf-8") == "{}"
