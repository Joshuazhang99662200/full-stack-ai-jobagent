# ruff: noqa: RUF001
import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from jobagent.bridge import feishu_approval, feishu_paged_approval
from jobagent.bridge.greeting_context import _card_feedback
from jobagent.jobs.sourcing_feedback import build_feedback_strategy
from jobagent.schemas.sourcing_feedback import SourcingFeedback
from jobagent.storage.database import Database
from jobagent.storage.feedback_repository import SqliteFeedbackRepository
from jobagent.storage.job_repository import SqliteJobRepository
from jobagent.storage.outreach_repository import SqliteOutreachRepository
from tests.bridge.test_feishu_paged_approval import OWNER, event, prepared
from tests.bridge.test_greeting_context import NOW, populated


@pytest.mark.parametrize("action,edited", [("revise", False), ("revise", True), ("approve", True)])
def test_revise_keeps_jd_positive_and_exact_draft_pair_without_approval(tmp_path, action, edited):
    path, batch_id = prepared(tmp_path)
    db = Database(path)
    store = SqliteOutreachRepository(db)
    batch = store.get_batch(batch_id)
    original = batch.items[0].text
    words = "请突出实际产品和用户。" if edited else original
    outcome = feishu_approval.handle_card_event(
        path, event(action, greeting=words, reason="copy", note="文案需要调整"), owner=OWNER,
    )
    assert outcome.status == "revision_requested" and outcome.approval_id is None
    state = feishu_paged_approval.load_state(path, "om_paged")
    assert state.decisions == {"1": "revision_requested"} and not state.approved_batches
    feedback = SqliteFeedbackRepository(db).events()
    assert len(feedback) == 1
    signal = feedback[0]
    job = SqliteJobRepository(db).get_job(batch.items[0].job_id)
    assert signal.action == "revise" and signal.candidate_id == "CAND_SYNTHETIC"
    assert signal.original_text == original and signal.revised_text == words
    assert signal.jd_text == job.jd_raw and signal.job_title == job.title
    assert signal.company == job.company
    assert "重新生成" in " ".join(outcome.lines) and "独立复核" in " ".join(outcome.lines)
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM outreach_approvals").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM evidence_items").fetchone()[0] == 0
    again = feishu_approval.handle_card_event(path, event(action, greeting=words), owner=OWNER)
    assert again.status == "duplicate" and len(SqliteFeedbackRepository(db).events()) == 1


def test_unchanged_acceptance_is_positive_for_jd_and_copy(tmp_path):
    path, _ = prepared(tmp_path)
    result = feishu_approval.handle_card_event(path, event("approve"), owner=OWNER)
    assert result.status == "registered"
    signal = SqliteFeedbackRepository(Database(path)).events()[0]
    assert signal.action == "approve" and signal.candidate_id == "CAND_SYNTHETIC"
    assert signal.original_text and signal.revised_text is None and signal.jd_text
    plan = build_feedback_strategy("boss", ["Agent"], [signal], previous="v1",
                                   candidate_id=signal.candidate_id, actor_id=signal.actor_id)
    assert plan.generator_feedback_ids == [signal.event_id] and not plan.deprioritized_job_ids


def test_decline_without_reason_only_downranks_this_jd_and_does_not_judge_copy(tmp_path):
    path, batch_id = prepared(tmp_path)
    result = feishu_approval.handle_card_event(path, event("decline"), owner=OWNER)
    assert result.status == "declined"
    signal = SqliteFeedbackRepository(Database(path)).events()[0]
    assert signal.action == "decline" and signal.candidate_id == "CAND_SYNTHETIC"
    job_id = SqliteOutreachRepository(Database(path)).get_batch(batch_id).items[0].job_id
    plan = build_feedback_strategy("boss", ["Agent", "AI"], [signal], previous="v1",
                                   candidate_id=signal.candidate_id, actor_id=signal.actor_id)
    assert plan.deprioritized_job_ids == [job_id]
    assert plan.generator_feedback_ids == [] and plan.query_penalties == {}
    assert plan.ordered_queries == ["Agent", "AI"]


def signal(action, *, eid, at, **updates):
    return SourcingFeedback(
        event_id=eid, job_id="JOB_FIXTURE", source="boss", search_term="Agent",
        query_strategy_version="v1", action=action, content_digest="sha256:fixture",
        actor_id="OWNER", occurred_at=at, idempotency_key=eid, candidate_id="CAND_TEST",
        original_text="Original greeting", revised_text="Revised greeting" if action == "revise"
        else None, jd_text="Build document agents.", job_title="Agent Product", company="Fixture",
        **updates,
    )


def test_revise_restores_jd_preference_and_tracks_negative_original_copy():
    now = datetime.now(UTC)
    old = signal("decline", eid="old", at=now)
    new = signal("revise", eid="new", at=now + timedelta(seconds=1))
    result = build_feedback_strategy("boss", ["Agent"], [old, new], previous="v1",
                                     candidate_id="CAND_TEST", actor_id="OWNER")
    assert not result.deprioritized_job_ids and result.generator_feedback_ids == ["new"]
    assert not result.query_penalties


def test_candidate_bound_decline_does_not_leak_into_copy_or_query_penalties():
    now = datetime.now(UTC)
    events = [
        signal("decline", eid=f"new{i}", at=now, reason_category="direction",
               free_text="This role is not suitable").model_copy(update={"job_id": f"JOB_{i}"})
        for i in range(3)
    ]
    result = build_feedback_strategy("boss", ["Agent", "AI"], events, previous="v1",
                                     candidate_id="CAND_TEST", actor_id="OWNER")
    assert result.query_penalties == {} and len(result.deprioritized_job_ids) == 3
    copy = signal("decline", eid="copy", at=now, reason_category="copy")
    result = build_feedback_strategy("boss", ["Agent"], [copy], previous="v1",
                                     candidate_id="CAND_TEST", actor_id="OWNER")
    assert result.generator_feedback_ids == [] and result.deprioritized_job_ids == ["JOB_FIXTURE"]


@pytest.mark.parametrize("field", ["candidate_id", "original_text", "revised_text", "jd_text"])
def test_revise_requires_bound_candidate_and_original_revision_jd_snapshot(field):
    data = signal("revise", eid="fixture", at=datetime.now(UTC)).model_dump()
    data[field] = None
    with pytest.raises(ValidationError):
        SourcingFeedback.model_validate(data)


def test_card_has_three_distinct_preference_actions_and_revision_status(tmp_path):
    path, _ = prepared(tmp_path)
    card = json.dumps(feishu_paged_approval.current_card(path, "om_paged"), ensure_ascii=False)
    for label in ["接受原稿", "接受JD，修改招呼", "JD不适合"]:
        assert label in card
    outcome = feishu_approval.handle_card_event(path, event("revise"), owner=OWNER)
    assert outcome.status == "revision_requested"
    shown = json.dumps(outcome.card, ensure_ascii=False)
    assert "独立复核" in shown and "发送权" in shown


@pytest.mark.parametrize("mode", ["stranger", "stale", "demo"])
def test_invalid_or_demo_revision_never_creates_real_preferences_or_approval(tmp_path, mode):
    path, _ = prepared(tmp_path)
    submitted = event("revise", greeting="Edited")
    if mode == "stranger":
        submitted["operator_id"] = "FOREIGN"
    elif mode == "stale":
        submitted["action_name"] = "revise_0_99"
    else:
        db = Database(path)
        with db.connect() as conn, conn:
            conn.execute("UPDATE paged_card_states SET state_json = "
                         "json_set(state_json, '$.demo_mode', json('true'))")
    result = feishu_approval.handle_card_event(path, submitted, owner=OWNER)
    assert result.status in {"rejected", "updated"}
    assert SqliteFeedbackRepository(Database(path)).events() == []
    with Database(path).connect() as conn:
        assert conn.execute("SELECT count(*) FROM outreach_approvals").fetchone()[0] == 0


def test_revision_signal_does_not_depend_on_approval_or_review_succeeding(tmp_path, monkeypatch):
    path, _ = prepared(tmp_path)

    def no_approval(*args, **kwargs):
        raise AssertionError("Revision intent must be saved before any approval attempt.")

    monkeypatch.setattr(feishu_paged_approval, "_approve_one", no_approval)
    outcome = feishu_approval.handle_card_event(
        path, event("approve", greeting="Replace the original text"), owner=OWNER,
    )
    assert outcome.status == "revision_requested"
    assert SqliteFeedbackRepository(Database(path)).events()[0].action == "revise"


def test_revision_event_and_state_are_atomic_if_feedback_storage_fails(tmp_path):
    path, _ = prepared(tmp_path)
    db = Database(path)
    with db.connect() as conn, conn:
        conn.execute("CREATE TRIGGER reject_signal BEFORE INSERT ON sourcing_feedback_events "
                     "BEGIN SELECT RAISE(ABORT, 'synthetic write failure'); END")
    result = feishu_approval.handle_card_event(path, event("revise"), owner=OWNER)
    assert result.status == "rejected"
    state = feishu_paged_approval.load_state(path, "om_paged")
    assert state.revision == 0 and state.decisions == {}
    assert SqliteFeedbackRepository(db).events() == []
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM paged_card_events").fetchone()[0] == 0


def test_raw_context_keeps_revision_requested_and_exact_original_revision_pair(tmp_path):
    path, job_id = populated(tmp_path, approved=False)
    db = Database(path)
    store = SqliteOutreachRepository(db)
    batch = store.get_batch("OBATCH_FIXTURE")
    with db.connect() as conn:
        ask_id = conn.execute("SELECT ask_id FROM outreach_asks").fetchone()[0]
    feishu_paged_approval.register_paged_card(
        path, "om_paged", ask_id=ask_id, batch_id=batch.batch_id, candidate_id="CAND_TEST",
    )
    revised = "Please emphasize document research instead of coding."
    result = feishu_approval.handle_card_event(
        path, event("revise", greeting=revised), owner=OWNER, now=NOW,
    )
    assert result.status == "revision_requested"
    job = SqliteJobRepository(db).get_job(job_id)
    with sqlite3.connect(path) as conn:
        feedback = _card_feedback(conn, "CAND_TEST", {job_id: job}, {"EVID_CURRENT"})
    assert len(feedback) == 1 and "revise/other" in feedback[0]
    assert batch.items[0].text in feedback[0] and revised in feedback[0]
