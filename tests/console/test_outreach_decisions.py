"""Every conversation and the panel read the same per-item approval state."""

import json
from datetime import timedelta

from typer.testing import CliRunner

from jobagent.cli.app import app
from jobagent.console.projection import snapshot
from jobagent.schemas.outreach import OutreachAudit, OutreachResult
from jobagent.storage.database import Database
from jobagent.storage.outreach_repository import SqliteOutreachRepository
from tests.bridge.test_greeting_context import NOW
from tests.bridge.test_panel_decisions import decision, record, two_item_list


def test_snapshot_shows_awaiting_declined_approved_withdrawn_and_sent_items(tmp_path):
    path, _ = two_item_list(tmp_path)
    view = snapshot(path, tmp_path, "CAND_TEST", now=NOW).approvals
    awaiting = [a for a in view if a.batch_id == "OBATCH_TWO"]
    assert [(a.number, a.state) for a in awaiting] == [
        (1, "awaiting_answer"), (2, "awaiting_answer"),
    ]
    assert [a.state for a in view if a.batch_id == "OBATCH_FIXTURE"] == ["withdrawn"]

    record(path, decision(path, "decline"))
    store = SqliteOutreachRepository(Database(path))
    second = store.get_batch("OBATCH_TWO").items[1]
    approved = record(path, decision(
        path, "approve_material", key="OP_2", revision=second.item_digest, job_id="fixture-role"
    ))
    assert approved.status == "rejected"  # item 2 belongs to another job than this contact

    current = snapshot(path, tmp_path, "CAND_TEST", now=NOW).approvals
    view = {(a.batch_id, a.number): a for a in current}
    declined = view[("OBATCH_TWO", 1)]
    assert declined.state == "declined" and declined.decided_via == "item_decision"
    assert view[("OBATCH_TWO", 2)].state == "awaiting_answer"


def test_panel_approval_and_send_result_are_visible_once(tmp_path):
    from tests.bridge.test_panel_decisions import setup

    path, job_id = setup(tmp_path)
    assert record(path, decision(path, "approve_material")).status == "saved"
    store = SqliteOutreachRepository(Database(path))
    child = next(b for b in store.list_batches() if b.batch_id != "OBATCH_FIXTURE")
    approval = store.get_approval(child.batch_id)
    store.append_audit(OutreachAudit(
        audit_id="OAUDIT_PANEL_1", batch_id=child.batch_id, number=1, job_id=job_id,
        platform="boss", item_digest=child.items[0].item_digest,
        approval_id=approval.approval_id, approval_channel=approval.channel,
        result=OutreachResult.SENT, recorded_at=NOW + timedelta(hours=1),
    ))

    result = snapshot(path, tmp_path, "CAND_TEST", now=NOW + timedelta(hours=2))
    [item] = result.approvals
    assert (item.batch_id, item.state, item.decided_via) == (
        child.batch_id, "approved", "item_decision",
    )
    assert item.approval_attestation and "Muse" in item.approval_attestation
    assert item.send_result == "sent" and item.sent_at == NOW + timedelta(hours=1)
    source = next(s for s in result.sources if s.name == "approvals")
    assert source.status == "complete"
    assert snapshot(path, tmp_path, "CAND_OTHER", now=NOW).approvals == []


def test_console_list_cli_carries_the_approval_states(tmp_path):
    from tests.bridge.test_panel_decisions import setup

    path, _ = setup(tmp_path)
    record(path, decision(path, "decline"))
    result = CliRunner().invoke(app, [
        "console", "list", "CAND_TEST", "--database", str(path), "--workspace", str(tmp_path),
    ])
    assert result.exit_code == 0, result.stdout
    [item] = json.loads(result.stdout)["approvals"]
    assert item["state"] == "declined" and item["text"]
