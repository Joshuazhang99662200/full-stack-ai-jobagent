"""Synthetic integration checks for cached send evidence and observation-only tracking."""

import json
from datetime import UTC, datetime, timedelta

from typer.testing import CliRunner

from jobagent.cli.app import app
from jobagent.storage.database import Database
from jobagent.storage.outreach_repository import SqliteOutreachRepository
from jobagent.storage.sent_tracking_repository import SqliteSentTrackingRepository
from tests.jobs.test_sent_tracking import TEXT, outreach_records

runner = CliRunner()


def setup(tmp_path):
    path = tmp_path / "private.sqlite3"
    db = Database(path)
    db.migrate()
    batch, approval, audit = outreach_records()
    now = datetime.now(UTC) - timedelta(minutes=2)
    batch = batch.model_copy(update={"created_at": now})
    approval = approval.model_copy(update={"approved_at": now})
    audit = audit.model_copy(update={"recorded_at": now})
    repo = SqliteOutreachRepository(db)
    repo.save_batch(batch)
    repo.save_approval(approval)
    repo.append_audit(audit)
    return db, batch, audit, ["--database", str(path)]


def invoke_file(tmp_path, command, payload, db):
    path = tmp_path / "input.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return runner.invoke(app, ["tracking", command, str(path), *db])


def start(tmp_path, db, **changes):
    payload = {
        "candidate_id": "CAND_DEMO",
        "tracking_id": "TRACK_DEMO",
        "audit_id": "OAUDIT_DEMO",
        "readback_text": TEXT,
    }
    payload.update(changes)
    return invoke_file(tmp_path, "start", payload, db)


def test_start_reads_cached_approval_and_audit_and_never_echoes_text(tmp_path):
    database, _, _, db = setup(tmp_path)
    bad = start(tmp_path, db, readback_text="PRIVATE_SENTINEL")
    assert bad.exit_code == 1 and "PRIVATE_SENTINEL" not in bad.output
    assert SqliteSentTrackingRepository(database).list_records("CAND_DEMO") == []
    result = start(tmp_path, db)
    assert result.exit_code == 0, result.output
    state = json.loads(result.stdout)
    assert state["tracking_state"] == "awaiting_reply" and state["tracking_version"] == 2
    assert TEXT not in result.stdout
    again = start(tmp_path, db)
    assert again.exit_code == 0 and json.loads(again.stdout) == state
    status = runner.invoke(
        app, ["tracking", "status", "TRACK_DEMO", "--candidate", "CAND_OTHER", *db]
    )
    assert status.exit_code == 1


def test_missing_cached_send_cannot_create_tracking(tmp_path):
    database, _, _, db = setup(tmp_path)
    result = start(tmp_path, db, audit_id="OAUDIT_UNKNOWN")
    assert result.exit_code == 1
    assert SqliteSentTrackingRepository(database).list_records("CAND_DEMO") == []


def test_pending_is_lease_projection_and_creates_no_sent_record(tmp_path):
    database, batch, _, db = setup(tmp_path)
    # Use another approved item without a send audit.
    batch = batch.model_copy(
        update={
            "batch_id": "OBATCH_PENDING",
            "items": [batch.items[0].model_copy(update={"job_id": "JOB_DEMO_2"})],
        }
    )
    _, approval, _ = outreach_records()
    approval = approval.model_copy(
        update={"batch_id": batch.batch_id, "approval_id": "OAPPROVAL_PENDING"}
    )
    repo = SqliteOutreachRepository(database)
    repo.save_batch(batch)
    repo.save_approval(approval)
    args = ["tracking", "pending", batch.batch_id, "--session", "SESSION_DEMO", *db]
    before = runner.invoke(app, args)
    assert before.exit_code == 0, before.output
    assert json.loads(before.stdout)["1"] == "approved_pending_execution"
    repo.acquire_lease("boss", "SESSION_DEMO", now=datetime.now(UTC), ttl_seconds=120)
    after = runner.invoke(app, args)
    assert after.exit_code == 0, after.output
    assert json.loads(after.stdout)["1"] == "leased"
    assert SqliteSentTrackingRepository(database).list_records("CAND_DEMO") == []


def test_event_uses_existing_inbound_then_abandon_removes_due(tmp_path):
    database, _, _, db = setup(tmp_path)
    assert start(tmp_path, db).exit_code == 0
    now = datetime.now(UTC)
    payload = {
        "event_id": "TEVT_REPLY",
        "tracking_id": "TRACK_DEMO",
        "candidate_id": "CAND_DEMO",
        "expected_version": 2,
        "kind": "reply_confirmed",
        "observed_at": now.isoformat(),
        "observation_id": "OBS_REPLY",
        "evidence_reference": "CEVT_IN_1",
        "evidence_kind": "conversation_message",
        "conversation_id": "CONV_DEMO",
        "inbound_event_id": "CEVT_IN_1",
    }
    missing = invoke_file(tmp_path, "event", payload, db)
    assert missing.exit_code == 1
    from jobagent.storage.conversation_repository import SqliteConversationRepository
    from tests.jobs.test_sent_tracking import inbound_evidence

    conversation, inbound = inbound_evidence()
    conversation = conversation.model_copy(update={"opened_at": now})
    inbound = inbound.model_copy(
        update={
            "seq": 1,
            "recorded_at": now,
            "inbound": inbound.inbound.model_copy(update={"received_at": now}),
        }
    )
    store = SqliteConversationRepository(database)
    store.save_conversation(conversation)
    store.append_events([inbound])
    reply = invoke_file(tmp_path, "event", payload, db)
    assert reply.exit_code == 0, reply.output
    assert json.loads(reply.stdout)["tracking_state"] == "replied"
    payload.update(
        event_id="TEVT_ABANDON",
        kind="user_abandon",
        expected_version=3,
        observation_id="OBS_OWNER",
        evidence_reference="OWNER_1",
        evidence_kind="owner_message",
        owner_text="停止跟踪这个合成岗位",
        observed_at=datetime.now(UTC).isoformat(),
    )
    closed = invoke_file(tmp_path, "event", payload, db)
    assert closed.exit_code == 0, closed.output
    assert json.loads(closed.stdout)["tracking_state"] == "closed"
    due = runner.invoke(app, ["tracking", "due", "CAND_DEMO", *db])
    assert due.exit_code == 0 and json.loads(due.stdout) == []
    history = runner.invoke(
        app, ["tracking", "history", "TRACK_DEMO", "--candidate", "CAND_DEMO", *db]
    )
    assert history.exit_code == 0 and len(json.loads(history.stdout)) == 5
    report = runner.invoke(app, ["tracking", "report", "CAND_DEMO", *db])
    assert report.exit_code == 0
    assert json.loads(report.stdout)["changes_search_weights"] is False


def test_invalid_json_is_structured_without_private_input(tmp_path):
    _, _, _, db = setup(tmp_path)
    path = tmp_path / "invalid.json"
    path.write_text('{"PRIVATE_SENTINEL":', encoding="utf-8")
    result = runner.invoke(app, ["tracking", "start", str(path), *db])
    assert result.exit_code == 1 and "PRIVATE_SENTINEL" not in result.output
    assert json.loads(result.stdout)["error"]["code"]


def reply_events(database):
    from jobagent.jobs.jd_snapshot import canonical_digest
    from jobagent.schemas.conversation import ConversationEvent, EventKind, ReplyDraft, ReplyResult
    from jobagent.schemas.jobs import NormalizedJob
    from jobagent.storage.conversation_repository import SqliteConversationRepository
    from jobagent.storage.job_repository import SqliteJobRepository
    from tests.jobs.test_sent_tracking import inbound_evidence

    now = datetime.now(UTC) - timedelta(seconds=1)
    conversation, inbound = inbound_evidence()
    conversation = conversation.model_copy(update={"opened_at": now})
    inbound = inbound.model_copy(
        update={
            "seq": 1,
            "recorded_at": now,
            "inbound": inbound.inbound.model_copy(update={"received_at": now}),
        }
    )
    store = SqliteConversationRepository(database)
    store.save_conversation(conversation)
    draft = ReplyDraft(kind="answer", text="合成回复全文", in_reply_to=inbound.event_id)
    digest = canonical_digest(
        {"conversation": conversation.conversation_id, **draft.model_dump(mode="json")}
    )
    approval = ConversationEvent(
        event_id="CEVT_APPROVAL",
        conversation_id=conversation.conversation_id,
        seq=2,
        kind=EventKind.REPLY_APPROVED,
        recorded_at=now,
        reply=draft,
        reply_digest=digest,
        ask_id="CASK_DEMO",
        attestation="同意这条合成回复",
    )
    result = ConversationEvent(
        event_id="CEVT_RESULT",
        conversation_id=conversation.conversation_id,
        seq=3,
        kind=EventKind.REPLY_RESULT,
        recorded_at=now,
        reply_digest=digest,
        result=ReplyResult.SENT,
    )
    store.append_events([inbound, approval, result])
    job = NormalizedJob(
        id="JOB_DEMO_1",
        source="boss",
        source_job_id="synthetic",
        title="合成岗位",
        company="合成公司",
        location="合成城市",
        jd_raw="合成职位说明",
        url="https://example.com/synthetic/1",
        collected_at=now,
        provenance=[{"source": "boss", "source_id": "synthetic", "collected_at": now}],
    )
    SqliteJobRepository(database).save_job(job)
    return conversation, inbound, draft, result


def test_approved_reply_readback_opens_new_round_and_mismatch_pauses(tmp_path):
    database, _, _, db = setup(tmp_path)
    assert start(tmp_path, db).exit_code == 0
    conversation, inbound, draft, result = reply_events(database)
    payload = {
        "event_id": "TEVT_IN",
        "tracking_id": "TRACK_DEMO",
        "candidate_id": "CAND_DEMO",
        "expected_version": 2,
        "kind": "reply_confirmed",
        "observed_at": datetime.now(UTC).isoformat(),
        "observation_id": "OBS_IN",
        "evidence_reference": inbound.event_id,
        "evidence_kind": "conversation_message",
        "conversation_id": conversation.conversation_id,
        "inbound_event_id": inbound.event_id,
    }
    response = invoke_file(tmp_path, "event", payload, db)
    assert response.exit_code == 0, response.output
    payload.update(
        event_id="TEVT_SENT",
        expected_version=3,
        kind="reply_sent",
        observation_id="OBS_SEND",
        evidence_reference=result.event_id,
        evidence_kind="send_audit",
        reply_result_event_id=result.event_id,
        readback_text=draft.text,
        observed_at=datetime.now(UTC).isoformat(),
    )
    # A mismatch pauses the current state without falsely starting a waiting round.
    bad = invoke_file(tmp_path, "event", {**payload, "readback_text": "PRIVATE_SENTINEL"}, db)
    assert bad.exit_code == 1 and "PRIVATE_SENTINEL" not in bad.output
    current = SqliteSentTrackingRepository(database).get("TRACK_DEMO", "CAND_DEMO")
    assert current.paused and current.round_number == 1 and current.tracking_state == "replied"
    resume = {
        **payload,
        "event_id": "TEVT_RESUME",
        "expected_version": 4,
        "kind": "resume",
        "observation_id": "OBS_RESUME",
        "evidence_kind": "owner_message",
        "owner_text": "确认回读后继续",
        "observed_at": datetime.now(UTC).isoformat(),
    }
    assert invoke_file(tmp_path, "event", resume, db).exit_code == 0
    payload.update(
        event_id="TEVT_SENT_OK", expected_version=5, observed_at=datetime.now(UTC).isoformat()
    )
    good = invoke_file(tmp_path, "event", payload, db)
    assert good.exit_code == 0, good.output
    state = json.loads(good.stdout)
    assert state["tracking_state"] == "awaiting_reply" and state["round_number"] == 2
    assert state["check_count"] == 0 and draft.text not in good.stdout
