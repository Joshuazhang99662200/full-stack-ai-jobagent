# ruff: noqa: RUF001  -- the person's answer is quoted verbatim in Chinese.
"""Host-neutral owner feedback on an asked outreach list feeds memory, never approval."""

import json
import sqlite3
from datetime import timedelta

import pytest
from typer.testing import CliRunner

from jobagent.bridge.greeting_context import load_greeting_request
from jobagent.bridge.preference_memory import load_preference_events
from jobagent.cli.app import app
from jobagent.errors import ContractValidationError
from jobagent.jobs.sourcing_feedback import build_feedback_strategy
from jobagent.schemas.sourcing_feedback import OutreachFeedbackRequest
from jobagent.storage.database import Database
from jobagent.storage.feedback_repository import SqliteFeedbackRepository
from jobagent.storage.outreach_repository import SqliteOutreachRepository
from tests.bridge.test_greeting_context import NOW, populated, settings

ORIGINAL = "Hello, I built research agents. Can we talk?"


def request(path, **item):
    with sqlite3.connect(path) as conn:
        ask_id = conn.execute("SELECT ask_id FROM outreach_asks").fetchone()[0]
    values = {"number": 1, "action": "decline", **item}
    return OutreachFeedbackRequest(
        batch_id="OBATCH_FIXTURE",
        ask_id=ask_id,
        candidate_id="CAND_TEST",
        actor_id="OWNER_SYNTHETIC",
        attestation="第 1 条先不发，方向不对。",
        occurred_at=NOW + timedelta(minutes=1),
        items=[values],
    )


def record(path, feedback):
    return SqliteFeedbackRepository(Database(path)).record_outreach_feedback(feedback)


def test_decline_reaches_preference_events_and_downranks_only_that_job(tmp_path):
    path, job_id = populated(tmp_path, approved=False)
    receipt = record(path, request(path, reason_category="direction", free_text="不做纯工具"))

    assert [item.status for item in receipt.items] == ["stored"]
    events = load_preference_events(path, "CAND_TEST")
    assert [event.event_id for event in events] == [receipt.items[0].event_id]
    event = events[0]
    assert event.action == "decline" and event.job_id == job_id
    assert event.original_text == ORIGINAL and event.revised_text is None
    plan = build_feedback_strategy(
        event.source, ["Agent"], events, previous="v1",
        candidate_id="CAND_TEST", actor_id=event.actor_id,
    )
    assert plan.deprioritized_job_ids == [job_id]
    assert plan.query_penalties == {}


def test_revision_reaches_greeting_context_without_approval(tmp_path):
    path, job_id = populated(tmp_path, approved=False)
    revised = "Hello, I evaluate grounded research agents. Shall we talk?"
    record(path, request(path, action="revise", revised_text=revised, reason_category="copy"))

    feedback = load_greeting_request(path, settings(), job_id=job_id).feedback
    assert len(feedback) == 1
    assert ORIGINAL in feedback[0] and revised in feedback[0]
    assert "OWNER_SYNTHETIC" not in feedback[0]
    assert SqliteOutreachRepository(Database(path)).get_approval("OBATCH_FIXTURE") is None


def test_approve_signal_must_mirror_a_recorded_approval(tmp_path):
    path, _ = populated(tmp_path, approved=False)
    with pytest.raises(ContractValidationError, match="approval"):
        record(path, request(path, action="approve"))

    (tmp_path / "approved").mkdir()
    path, _ = populated(tmp_path / "approved", approved=True)
    receipt = record(path, request(path, action="approve"))
    assert receipt.items[0].status == "stored"
    assert load_preference_events(path, "CAND_TEST")[0].action == "approve"


def test_decline_cannot_contradict_an_approved_item(tmp_path):
    path, _ = populated(tmp_path, approved=True)
    with pytest.raises(ContractValidationError, match="approved"):
        record(path, request(path, action="decline"))


@pytest.mark.parametrize(
    "item",
    [
        {"number": 9},
        {"action": "revise", "revised_text": ORIGINAL},
    ],
)
def test_unknown_items_and_unchanged_revisions_are_rejected(tmp_path, item):
    path, _ = populated(tmp_path, approved=False)
    with pytest.raises(ContractValidationError):
        record(path, request(path, **item))
    assert load_preference_events(path, "CAND_TEST") == []


def test_feedback_before_the_question_was_asked_is_rejected(tmp_path):
    path, _ = populated(tmp_path, approved=False)
    early = request(path).model_copy(update={"occurred_at": NOW - timedelta(minutes=1)})
    with pytest.raises(ContractValidationError, match="asked"):
        record(path, early)


def test_replay_is_idempotent_and_a_second_decision_conflicts(tmp_path):
    path, _ = populated(tmp_path, approved=False)
    first = record(path, request(path))
    again = record(path, request(path))
    assert again.items[0].event_id == first.items[0].event_id
    assert again.items[0].status == "duplicate"
    with pytest.raises(ContractValidationError, match="already"):
        record(path, request(path, action="revise", revised_text="A different greeting."))
    assert len(load_preference_events(path, "CAND_TEST")) == 1


def test_feedback_from_another_candidate_is_rejected(tmp_path):
    path, _ = populated(tmp_path, approved=False)
    foreign = request(path).model_copy(update={"candidate_id": "CAND_OTHER"})
    with pytest.raises(ContractValidationError, match="candidate"):
        record(path, foreign)


def test_cli_records_feedback_and_reports_no_permission(tmp_path):
    path, _ = populated(tmp_path, approved=False)
    request_path = tmp_path / "feedback.json"
    request_path.write_text(request(path).model_dump_json(), encoding="utf-8")

    result = CliRunner().invoke(
        app, ["outreach", "feedback", str(request_path), "--database", str(path)]
    )

    assert result.exit_code == 0, result.stdout
    receipt = json.loads(result.stdout)
    assert receipt["items"][0]["status"] == "stored"
    assert receipt["grants_approval"] is False
