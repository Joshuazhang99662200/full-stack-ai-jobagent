import json
from datetime import UTC, datetime, timedelta

from typer.testing import CliRunner

from jobagent.cli.app import app

runner = CliRunner()


def invoke(tmp_path, action, payload):
    path = tmp_path / "input.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return runner.invoke(
        app, ["intake", action, str(path), "--database", str(tmp_path / "private.sqlite3")]
    )


def test_chat_intake_next_returns_recoverable_action_contract_and_private_context(tmp_path):
    from tests.storage.test_job_intake import request

    req = request(occurred_at=datetime.now(UTC) - timedelta(seconds=2))
    result = invoke(tmp_path, "enqueue", req.model_dump(mode="json"))
    assert result.exit_code == 0, result.output
    row = json.loads(result.stdout)
    assert row["next_actions"] == ["resolve_target"]
    assert req.owner_text not in result.stdout
    args = [
        "intake",
        "next",
        row["intake_id"],
        "--candidate",
        "CAND_DEMO",
        "--database",
        str(tmp_path / "private.sqlite3"),
    ]
    next_result = runner.invoke(app, args)
    assert next_result.exit_code == 0, next_result.output
    handoff = json.loads(next_result.stdout)
    assert handoff["actions"][0]["action"] == "resolve_target"
    assert handoff["actions"][0]["input"]["expected_version"] == row["version"]
    assert handoff["actions"][0]["contract"] == "IntakeResolve"
    repeat = runner.invoke(app, args)
    assert json.loads(repeat.stdout)["actions"] == handoff["actions"]


def test_recover_existing_jd_and_factorization_then_activate_next_plan_through_cli(tmp_path):
    from jobagent.jobs.lexicon import serialize_lexicon
    from tests.storage.test_job_intake import NOW
    from tests.storage.test_job_intake_service import full, policy

    service, row, _ = full(tmp_path)
    # Real program time follows the synthetic queue timestamps.
    path = tmp_path / "lexicon.md"
    path.write_text(serialize_lexicon(policy()), encoding="utf-8")
    payload = {
        "event_id": "CLI_FACTOR",
        "intake_id": row.intake_id,
        "candidate_id": row.candidate_id,
        "expected_version": row.version,
    }
    input_path = tmp_path / "factor.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")
    db = ["--database", str(tmp_path / "private.sqlite3")]
    result = runner.invoke(app, ["intake", "factorize", str(input_path), str(path), *db])
    assert result.exit_code == 0, result.output
    state = json.loads(result.stdout)
    assert state["signal_id"] and state["feature_set_id"]
    handoff = runner.invoke(
        app, ["intake", "next", row.intake_id, "--candidate", row.candidate_id, *db]
    )
    assert handoff.exit_code == 0, handoff.output
    context = json.loads(handoff.stdout)["context"]
    assert context["snapshot"]["jd_text"] and context["confirmed_evidence"] == []
    assert "OWNER" not in handoff.stdout
    strategy_input = tmp_path / "strategy.json"
    strategy_input.write_text(
        json.dumps(
            {
                "candidate_id": row.candidate_id,
                "domain": row.domain,
                "source": "boss",
                "baseline_queries": ["设计师"],
            }
        ),
        encoding="utf-8",
    )
    updated = runner.invoke(app, ["intake", "strategy", str(strategy_input), str(path), *db])
    assert updated.exit_code == 0, updated.output
    assert json.loads(updated.stdout)["plan"]["status"] == "needs_seed"
    active = runner.invoke(app, ["intake", "active", row.candidate_id, row.domain, "boss", *db])
    assert active.exit_code == 0
    assert json.loads(active.stdout)["markdown"]
    listing = runner.invoke(app, ["intake", "list", row.candidate_id, row.domain, *db])
    assert listing.exit_code == 0 and len(json.loads(listing.stdout)) == 1
    history = runner.invoke(
        app, ["intake", "history", row.intake_id, "--candidate", row.candidate_id, *db]
    )
    assert history.exit_code == 0
    assert all("owner_text" not in e["state"] for e in json.loads(history.stdout))
    assert service.repository.get(row.intake_id, row.candidate_id).updated_at >= NOW


def test_invalid_input_never_echoes_private_source_text(tmp_path):
    result = invoke(tmp_path, "enqueue", {"owner_text": "PRIVATE_SENTINEL"})
    assert result.exit_code == 1 and "PRIVATE_SENTINEL" not in result.output
    assert json.loads(result.stdout)["error"]["code"]


def test_only_existing_evidence_can_be_passed_to_review_and_batch_commands(tmp_path):
    from tests.storage.test_job_intake_service import command, full

    service, row, _ = full(tmp_path)
    result = invoke(tmp_path, "batch", command(row, batch_id="OBATCH_FAKE"))
    assert result.exit_code == 1
    assert service.outreach.get_approval("OBATCH_FAKE") is None


def test_list_selector_mapping_has_an_explicit_cli_boundary(tmp_path):
    from tests.storage.test_job_intake import NOW
    from tests.storage.test_job_intake_service import full

    service, row, _ = full(tmp_path)
    payload = dict(
        candidate_id="CAND_DEMO",
        platform="boss",
        list_version="CLI_LIST",
        message_reference="MSG_LIST",
        observed_at=NOW.isoformat(),
        targets={"35": row.job_id},
    )
    result = invoke(tmp_path, "selection", payload)
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["target_count"] == 1
    assert invoke(tmp_path, "selection", payload).exit_code == 0
    changed = invoke(tmp_path, "selection", {**payload, "targets": {"36": row.job_id}})
    assert changed.exit_code == 1
    assert service.repository.get(row.intake_id, row.candidate_id).job_id == row.job_id
