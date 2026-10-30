# ruff: noqa: RUF001
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from jobagent.bridge import feishu_approval
from jobagent.storage.database import Database
from jobagent.storage.outreach_repository import SqliteOutreachRepository
from tests.cli.test_outreach import drafted, invoke

OWNER = "ou_synthetic_owner"


def prepared(tmp_path: Path) -> tuple[Path, str]:
    from jobagent.bridge.feishu_paged_approval import register_paged_card
    from jobagent.schemas.candidate import CandidateProfile
    from jobagent.storage.candidate_repository import SqliteCandidateRepository

    database, batch_id = drafted(tmp_path)
    _, ask = invoke("outreach", "ask", batch_id, "--database", str(database))
    assert isinstance(ask, dict)
    SqliteCandidateRepository(Database(database)).save_profile(CandidateProfile(id="CAND_SYNTHETIC"))
    register_paged_card(database, "om_paged", ask_id=ask["ask_id"], batch_id=batch_id,
                        candidate_id="CAND_SYNTHETIC")
    return database, batch_id


def event(action: str, page: int = 0, revision: int = 0, **fields: Any) -> dict[str, Any]:
    return {
        "event_id": f"ev_{action}_{page}_{revision}", "operator_id": OWNER,
        "message_id": "om_paged", "action_tag": "button",
        "action_name": f"{action}_{page}_{revision}", "token": "synthetic_token",
        "form_value": json.dumps(fields, ensure_ascii=False),
    }


def test_navigation_preserves_edits_and_never_approves(tmp_path: Path) -> None:
    from jobagent.bridge.feishu_paged_approval import load_state

    database, batch_id = prepared(tmp_path)
    outcome = feishu_approval.handle_card_event(
        database, event("next", greeting="本人编辑的草稿"), owner=OWNER,
    )
    assert outcome.status == "updated"
    state = load_state(database, "om_paged")
    assert state is not None and state.page == 1 and state.drafts["1"] == "本人编辑的草稿"
    assert SqliteOutreachRepository(Database(database)).get_approval(batch_id) is None
    back = feishu_approval.handle_card_event(
        database, event("previous", 1, 1, greeting="第二条草稿"), owner=OWNER,
    )
    assert back.status == "updated"
    assert "本人编辑的草稿" in json.dumps(back.card, ensure_ascii=False)


def test_changed_words_save_revision_signal_and_preserve_other_item(tmp_path: Path) -> None:
    from jobagent.bridge.feishu_paged_approval import load_state

    database, original = prepared(tmp_path)
    final = "您好，我主导过 Agent 产品开发，也做过模型评测。方便聊聊吗？"
    outcome = feishu_approval.handle_card_event(
        database, event("approve", greeting=final), owner=OWNER,
    )
    assert outcome.status == "revision_requested" and outcome.approval_id is None
    state = load_state(database, "om_paged")
    assert state is not None and state.decisions == {"1": "revision_requested"}
    assert not state.closed and not state.approved_batches
    store = SqliteOutreachRepository(Database(database))
    assert store.get_approval(original) is None
    from jobagent.storage.feedback_repository import SqliteFeedbackRepository

    feedback = SqliteFeedbackRepository(Database(database)).events()
    assert len(feedback) == 1 and feedback[0].action == "revise"
    assert feedback[0].revised_text == final
    again = feishu_approval.handle_card_event(
        database, event("approve", greeting=final), owner=OWNER,
    )
    assert again.status == "duplicate"


def test_explicit_decline_is_feedback_and_cannot_approve(tmp_path: Path) -> None:
    from jobagent.bridge.feishu_paged_approval import load_state
    from jobagent.storage.feedback_repository import SqliteFeedbackRepository

    database, batch_id = prepared(tmp_path)
    outcome = feishu_approval.handle_card_event(
        database, event("decline", greeting="草稿", reason="copy", note="文案太长"), owner=OWNER,
    )
    assert outcome.status == "declined"
    state = load_state(database, "om_paged")
    assert state is not None and state.decisions == {"1": "declined"}
    store = SqliteOutreachRepository(Database(database))
    assert store.get_approval(batch_id) is None and state.approved_batches == {}
    feedback = SqliteFeedbackRepository(Database(database)).events()
    assert len(feedback) == 1 and feedback[0].reason_category == "copy"
    assert feedback[0].free_text == "文案太长" and feedback[0].affects_sourcing
    assert feedback[0].candidate_id is not None


def test_stranger_stale_page_and_expired_card_do_not_mutate(tmp_path: Path) -> None:
    from jobagent.bridge.feishu_paged_approval import load_state

    database, _ = prepared(tmp_path)
    foreign = event("approve", greeting="valid")
    foreign["operator_id"] = "ou_other"
    assert feishu_approval.handle_card_event(database, foreign, owner=OWNER).status == "rejected"
    stale = event("approve", 1, 7, greeting="valid")
    assert feishu_approval.handle_card_event(database, stale, owner=OWNER).status == "rejected"
    state = load_state(database, "om_paged")
    assert state is not None
    expired = feishu_approval.handle_card_event(
        database, event("approve", greeting="valid"), owner=OWNER,
        now=datetime.now(UTC) + timedelta(days=2),
    )
    assert expired.status == "rejected" and "过期" in expired.lines[0]
    assert load_state(database, "om_paged").decisions == {}  # type: ignore[union-attr]


def test_new_card_has_all_decision_fields_and_one_visible_job(tmp_path: Path) -> None:
    from jobagent.bridge.feishu_paged_approval import current_card

    database, _ = prepared(tmp_path)
    card = current_card(database, "om_paged")
    text = json.dumps(card, ensure_ascii=False)
    assert "alpha" in text and "beta" not in text
    for label in ("薪资", "base", "JD 要点", "匹配", "适合理由", "缺口", "接受原稿",
                  "接受JD，修改招呼", "JD不适合", "下一条"):
        assert label in text
    assert '"name": "greeting"' in text and "上一条" in text


def test_all_decisions_close_original_question_without_approving_it(tmp_path: Path) -> None:
    from jobagent.bridge.feishu_paged_approval import load_state

    database, batch_id = prepared(tmp_path)
    first = feishu_approval.handle_card_event(
        database, event("decline", reason="job_dislike"), owner=OWNER,
    )
    second = feishu_approval.handle_card_event(
        database, event("decline", 1, 1, reason="later"), owner=OWNER,
    )
    assert first.status == second.status == "declined"
    state = load_state(database, "om_paged")
    assert state is not None and state.closed
    store = SqliteOutreachRepository(Database(database))
    assert store.is_withdrawn(batch_id) and store.get_approval(batch_id) is None
    assert store.list_audits() == []


def test_current_job_change_invalidates_approval_not_question_content(tmp_path: Path) -> None:
    from jobagent.storage.job_repository import SqliteJobRepository

    database, batch_id = prepared(tmp_path)
    batch = SqliteOutreachRepository(Database(database)).get_batch(batch_id)
    assert batch is not None
    jobs = SqliteJobRepository(Database(database))
    job = jobs.get_job(batch.items[0].job_id)
    assert job is not None
    jobs.save_job(job.model_copy(update={"jd_raw": job.jd_raw + "changed"}))
    outcome = feishu_approval.handle_card_event(database, event("approve"), owner=OWNER)
    assert outcome.status == "rejected" and "变化" in outcome.lines[0]
    assert SqliteOutreachRepository(Database(database)).get_approval(batch_id) is None


def test_decline_feedback_is_consumed_at_next_explicit_fetch(tmp_path: Path) -> None:
    from jobagent.bridge.sourcing_feedback import next_fetch_strategy
    from jobagent.storage.feedback_repository import SqliteFeedbackRepository

    database, batch_id = prepared(tmp_path)
    feishu_approval.handle_card_event(
        database, event("decline", reason="job_dislike"), owner=OWNER,
    )
    batch = SqliteOutreachRepository(Database(database)).get_batch(batch_id)
    assert batch is not None
    plan = next_fetch_strategy(database, "boss", ["Agent"], previous_version="owner_strategy",
                               candidate_id="CAND_SYNTHETIC", actor_id=OWNER)
    assert plan.deprioritized_job_ids == [batch.items[0].job_id]
    assert plan.previous_version == "owner_strategy" and not plan.changes_hard_constraints
    events = SqliteFeedbackRepository(Database(database)).events()
    assert plan.applied_feedback_ids == [events[0].event_id]
    with Database(database).connect() as connection:
        assert connection.execute(
            "SELECT version FROM sourcing_feedback_strategies WHERE version = ?", (plan.version,),
        ).fetchone() is not None


def test_demo_approval_and_decline_never_create_real_authority_or_preference(
    tmp_path: Path,
) -> None:
    from jobagent.bridge.feishu_paged_approval import current_card, register_paged_card
    from jobagent.storage.feedback_repository import SqliteFeedbackRepository

    database, batch_id = drafted(tmp_path)
    _, ask = invoke("outreach", "ask", batch_id, "--database", str(database))
    assert isinstance(ask, dict)
    register_paged_card(database, "om_paged", ask_id=ask["ask_id"], batch_id=batch_id,
                        demo_mode=True)
    assert "演示" in json.dumps(current_card(database, "om_paged"), ensure_ascii=False)
    outcome = feishu_approval.handle_card_event(database, event("approve"), owner=OWNER)
    assert outcome.status == "updated" and outcome.approval_id is None
    feishu_approval.handle_card_event(
        database, event("decline", 1, 1, reason="job_dislike", note="演示反馈"), owner=OWNER,
    )
    repository = SqliteFeedbackRepository(Database(database))
    state = repository.state("om_paged")
    assert state is not None and state.closed and state.approved_batches == {}
    assert state.feedback_drafts["2"]["note"] == "演示反馈"
    assert repository.events() == []
    with Database(database).connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM outreach_approvals").fetchone()[0] == 0


def test_normal_card_rechecks_current_canonical_evidence_before_approval(tmp_path: Path) -> None:
    from jobagent.bridge.feishu_paged_approval import register_paged_card
    from jobagent.outreach.service import OutreachService
    from jobagent.schemas.candidate import CandidateProfile
    from jobagent.schemas.outreach import OutreachDraft
    from jobagent.storage.candidate_repository import SqliteCandidateRepository
    from jobagent.storage.job_repository import SqliteJobRepository

    database, original_id = drafted(tmp_path)
    db = Database(database)
    store = SqliteOutreachRepository(db)
    original = store.get_batch(original_id)
    assert original is not None
    item = original.items[0]
    job = SqliteJobRepository(db).get_job(item.job_id)
    assert job is not None
    # The old batch was valid at draft time; its evidence is no longer canonical now.
    service = OutreachService()
    report = service.build_batch(
        [OutreachDraft(job_id=item.job_id, platform=item.platform, text=item.text,
                       evidence_ids=["EVID_REMOVED"])], jobs={item.job_id: job},
        already_contacted=set(), confirmed_evidence_ids={"EVID_REMOVED"},
        batch_id="OBATCH_OLD_EVIDENCE", created_at=datetime.now(UTC),
    )
    assert report.batch is not None
    batch = report.batch
    store.save_batch(batch)
    ask = service.ask(batch)
    store.save_ask(ask)
    SqliteCandidateRepository(db).save_profile(CandidateProfile(id="CAND_TEST"))
    register_paged_card(database, "om_paged", batch_id=batch.batch_id, ask_id=ask.ask_id,
                        candidate_id="CAND_TEST")
    outcome = feishu_approval.handle_card_event(database, event("approve"), owner=OWNER)
    assert outcome.status == "rejected"
    assert store.get_approval(batch.batch_id) is None
    with db.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM outreach_approvals").fetchone()[0] == 0
