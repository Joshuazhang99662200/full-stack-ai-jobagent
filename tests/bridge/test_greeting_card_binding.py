import json
from datetime import UTC, datetime

import pytest

from jobagent.bridge import feishu_approval, feishu_paged_approval
from jobagent.errors import JobAgentError
from jobagent.outreach.service import OutreachService
from jobagent.schemas.outreach import OutreachDraft
from jobagent.storage.job_repository import SqliteJobRepository
from jobagent.storage.outreach_repository import SqliteOutreachRepository
from tests.bridge.test_greeting_freshness import sources as sources

NOW = datetime(2026, 10, 26, 1, tzinfo=UTC)
OWNER = "ou_synthetic_owner"


def prepared(sources, *, paged):
    db, _, job, draft = sources
    service = OutreachService()
    report = service.build_batch(
        [draft], jobs={job.id: job}, already_contacted=set(),
        confirmed_evidence_ids={"EVID_A", "EVID_B"}, batch_id="OBATCH_CARD_BINDING",
        created_at=NOW,
    )
    batch = report.batch
    assert batch is not None
    ask = service.ask(batch, asked_at=NOW)
    store = SqliteOutreachRepository(db)
    store.save_batch(batch)
    store.save_ask(ask)
    feishu_approval.register_card(db.path, "om_bound", ask_id=ask.ask_id,
                                  batch_id=batch.batch_id)
    if paged:
        feishu_paged_approval.register_paged_card(
            db.path, "om_bound", ask_id=ask.ask_id, batch_id=batch.batch_id,
            candidate_id="CAND_TEST",
        )
    return db, batch


def event(*, paged, text):
    return {
        "event_id": "EVENT_BINDING", "operator_id": OWNER, "message_id": "om_bound",
        "action_tag": "button", "action_name": "approve_0_0" if paged else "submit",
        "form_value": json.dumps({"greeting": text} if paged else
                                 {"pick_1": True, "text_1": text}),
    }


def test_paged_original_ai_draft_is_approved_as_child_with_identical_source_binding(sources):
    db, batch = prepared(sources, paged=True)
    result = feishu_approval.handle_card_event(
        db.path, event(paged=True, text=batch.items[0].text), owner=OWNER, now=NOW,
    )
    assert result.status == "registered", result.lines
    state = feishu_paged_approval.load_state(db.path, "om_bound")
    assert state is not None
    store = SqliteOutreachRepository(db)
    child = store.get_batch(state.approved_batches["1"])
    assert child is not None
    assert child.items[0].source_binding == batch.items[0].source_binding
    assert child.items[0].text == batch.items[0].text
    assert store.get_approval(child.batch_id) is not None
    assert store.get_approval(batch.batch_id) is None


@pytest.mark.parametrize("paged", [False, True])
@pytest.mark.parametrize("change", ["evidence", "jd", "policy"])
def test_changed_ai_sources_never_produce_card_approval(sources, paged, change, monkeypatch):
    db, batch = prepared(sources, paged=paged)
    _, candidates, job, _ = sources
    if change == "evidence":
        item = candidates.get_evidence("CAND_TEST", "EVID_A")
        candidates.upsert_evidence("CAND_TEST", item.model_copy(update={
            "statement": "A changed source that was not reviewed.",
        }))
    elif change == "jd":
        SqliteJobRepository(db).save_job(job.model_copy(update={"jd_raw": "Changed job duties."}))
    else:
        monkeypatch.setattr("jobagent.bridge.greeting_freshness.read_reference", lambda _: "new")
    result = feishu_approval.handle_card_event(
        db.path, event(paged=paged, text=batch.items[0].text), owner=OWNER, now=NOW,
    )
    assert result.status == "rejected"
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM outreach_approvals").fetchone()[0] == 0


@pytest.mark.parametrize("paged", [False, True])
def test_card_edited_ai_draft_requires_regeneration_and_new_independent_review(sources, paged):
    db, batch = prepared(sources, paged=paged)
    result = feishu_approval.handle_card_event(
        db.path, event(paged=paged, text=batch.items[0].text + " Updated wording."),
        owner=OWNER, now=NOW,
    )
    assert result.status == ("revision_requested" if paged else "rejected")
    assert "重新生成" in " ".join(result.lines) and "独立复核" in " ".join(result.lines)
    if paged:
        state = feishu_paged_approval.load_state(db.path, "om_bound")
        assert state is not None and state.decisions == {"1": "revision_requested"}
        assert not state.approved_batches
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM outreach_approvals").fetchone()[0] == 0


def test_legacy_original_ai_draft_keeps_source_binding_in_approved_batch(sources):
    db, batch = prepared(sources, paged=False)
    result = feishu_approval.handle_card_event(
        db.path, event(paged=False, text=batch.items[0].text), owner=OWNER, now=NOW,
    )
    assert result.status == "registered", result.lines
    saved = SqliteOutreachRepository(db).get_batch(batch.batch_id)
    assert saved.items[0].source_binding == batch.items[0].source_binding


def test_approve_one_verifies_current_candidate_sources_before_rebuilding(sources):
    db, batch = prepared(sources, paged=True)
    _, candidates, _, _ = sources
    original = candidates.get_evidence("CAND_TEST", "EVID_A")
    candidates.upsert_evidence("CAND_TEST", original.model_copy(update={"user_confirmed": False}))
    with pytest.raises(JobAgentError):
        feishu_paged_approval._approve_one(
            db, batch, 0, batch.items[0].text, now=NOW, owner=OWNER,
            event_id="EVENT_DIRECT", message_id="om_bound", candidate_id="CAND_TEST",
        )


def test_old_legacy_unbound_card_still_approves_normally(sources):
    db, _, job, _ = sources
    draft = OutreachDraft(job_id=job.id, platform=job.source,
                          text="Hello, I built research agents. Can we talk?")
    service = OutreachService()
    batch = service.build_batch(
        [draft], jobs={job.id: job}, already_contacted=set(), confirmed_evidence_ids=set(),
        batch_id="OBATCH_OLD_CARD", created_at=NOW,
    ).batch
    store = SqliteOutreachRepository(db)
    store.save_batch(batch)
    ask = service.ask(batch, asked_at=NOW)
    store.save_ask(ask)
    feishu_approval.register_card(db.path, "om_bound", ask_id=ask.ask_id, batch_id=batch.batch_id)
    result = feishu_approval.handle_card_event(
        db.path, event(paged=False, text=draft.text), owner=OWNER, now=NOW,
    )
    assert result.status == "registered" and store.get_approval(batch.batch_id) is not None
