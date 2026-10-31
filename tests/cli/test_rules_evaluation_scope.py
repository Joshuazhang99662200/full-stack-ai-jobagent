import json
from datetime import timedelta

from typer.testing import CliRunner

from jobagent.cli.app import app
from jobagent.storage.database import Database
from tests.jobs.test_pipeline_contracts import NOW
from tests.rules.test_evaluation import profile
from tests.storage.test_pipeline_policy import activate


def evaluate(path, database, *extra):
    return CliRunner().invoke(
        app,
        [
            "rules",
            "evaluate",
            "backlog",
            "--rules-file",
            str(path),
            "--candidate",
            "CAND_DEMO",
            "--pending-review",
            "5",
            "--now",
            NOW.isoformat(),
            "--database",
            str(database),
            *extra,
        ],
    )


def test_current_evaluation_rejects_stale_export_and_historical_is_explicit(tmp_path):
    private = tmp_path / ".jobagent"
    private.mkdir()
    database = Database(private / "rules.sqlite3")
    database.migrate()
    old = activate(database, {"PENDING_BACKLOG_ASK_THRESHOLD": 2})
    path = private / "old.json"
    path.write_text(old.model_dump_json(), encoding="utf-8")
    # A real second confirmed version, with a newer provenance time than the first.
    from jobagent.rules.service import make_proposal
    from jobagent.schemas.dynamic_rules import RuleConfirmation
    from jobagent.storage.rule_repository import SqliteRuleRepository
    from tests.rules.test_dynamic_registry import request

    change = request("PENDING_BACKLOG_ASK_THRESHOLD", 4)
    change.candidate_id = "CAND_DEMO"
    change.provenance.decided_at = NOW - timedelta(hours=1)
    change.expected_version = old.version
    store = SqliteRuleRepository(database)
    proposed = make_proposal(change, old, now=change.provenance.decided_at)
    store.save_proposal(proposed)
    changed = store.approve(
        RuleConfirmation(
            proposal_id=proposed.proposal_id,
            question_digest=proposed.question_digest,
            answer="Synthetic exact new threshold",
            actor_id="synthetic owner",
            confirmed_at=change.provenance.decided_at,
        ),
        candidate_id="CAND_DEMO",
    )
    stale = evaluate(path, database.path)
    assert stale.exit_code != 0
    assert "stale" in stale.stdout.lower()
    replay = evaluate(path, database.path, "--historical")
    assert replay.exit_code == 0, replay.stdout
    result = json.loads(replay.stdout)
    assert result["snapshot_mode"] == "historical"
    assert not result["current_head_verified"] and not result["persisted"]
    assert result["rule_version"] == old.version != changed.version
    path.write_text(changed.model_dump_json(), encoding="utf-8")
    current = evaluate(path, database.path)
    assert current.exit_code == 0, current.stdout
    assert json.loads(current.stdout)["current_head_verified"]
    assert json.loads(current.stdout)["snapshot_mode"] == "current"


def test_current_evaluation_requires_existing_authority_and_remains_readonly(tmp_path):
    private = tmp_path / ".jobagent"
    private.mkdir()
    path = private / "unregistered.json"
    path.write_text(
        profile({"PENDING_BACKLOG_ASK_THRESHOLD": 2}, candidate_id="CAND_DEMO").model_dump_json(),
        encoding="utf-8",
    )
    absent = private / "absent.sqlite3"
    result = evaluate(path, absent)
    assert result.exit_code != 0 and not absent.exists()
    assert "authoritative" in result.stdout.lower()
    database = Database(private / "empty.sqlite3")
    database.migrate()
    before = database.path.read_bytes()
    result = evaluate(path, database.path)
    assert result.exit_code != 0
    assert "authoritative" in result.stdout.lower()
    assert database.path.read_bytes() == before


def test_current_evaluation_rejects_future_effective_profile(tmp_path):
    private = tmp_path / ".jobagent"
    private.mkdir()
    database = Database(private / "rules.sqlite3")
    database.migrate()
    current = activate(database, {"PENDING_BACKLOG_ASK_THRESHOLD": 2})
    path = private / "rules.json"
    path.write_text(current.model_dump_json(), encoding="utf-8")
    result = CliRunner().invoke(
        app,
        [
            "rules",
            "evaluate",
            "backlog",
            "--rules-file",
            str(path),
            "--candidate",
            "CAND_DEMO",
            "--pending-review",
            "5",
            "--database",
            str(database.path),
            "--now",
            (NOW - timedelta(days=2)).isoformat(),
        ],
    )
    assert result.exit_code != 0 and "future" in result.stdout.lower()
