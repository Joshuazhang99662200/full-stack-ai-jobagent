"""The panel reads back its own saved decisions through a read-only HostState."""

import json

from typer.testing import CliRunner

from jobagent.bridge.panel_decisions import panel_operation
from jobagent.cli.app import app
from jobagent.console.host_state import host_state
from jobagent.storage.database import Database
from jobagent.storage.outreach_repository import SqliteOutreachRepository
from tests.bridge.test_panel_decisions import PIPE, TEXT, decision, record, setup


def test_saved_decisions_are_readable_by_their_receipt_event_id(tmp_path):
    path, _ = setup(tmp_path)
    item = SqliteOutreachRepository(Database(path)).get_batch("OBATCH_FIXTURE").items[0]

    before = host_state(path, "CAND_TEST")
    [job] = before.jobs
    assert (job.job_id, job.contact_id) == ("fixture-role", PIPE)
    assert job.materials[-1].revision == item.item_digest and job.materials[-1].body == TEXT
    assert job.events == [] and before.receipts == []

    receipt = record(path, decision(path, "approve_material", key="OP_APPROVE"))
    after = host_state(path, "CAND_TEST")
    [job] = after.jobs
    [event] = job.events
    assert event.event_id == receipt.event_id and event.operation_key == "OP_APPROVE"
    assert event.kind == "approve_material" and event.material is not None
    assert event.material.revision == item.item_digest and event.material.body == TEXT
    assert [r.event_id for r in after.receipts] == [receipt.event_id]
    assert after.sync.status == "unavailable"  # todos, channels and batches come from the host


def test_operation_read_back_uses_the_stored_operation(tmp_path):
    path, _ = setup(tmp_path)
    receipt = record(path, decision(path, "decline", key="OP_DECLINE"))
    assert panel_operation(path, "CAND_TEST", "OP_DECLINE").event_id == receipt.event_id
    assert panel_operation(path, "CAND_OTHER", "OP_DECLINE").status == "rejected"


def test_other_candidates_see_nothing(tmp_path):
    path, _ = setup(tmp_path)
    record(path, decision(path, "decline"))
    assert host_state(path, "CAND_OTHER").jobs == []


def test_cli_exports_the_host_state(tmp_path):
    path, _ = setup(tmp_path)
    result = CliRunner().invoke(
        app, ["console", "host-state", "--candidate", "CAND_TEST", "--database", str(path)]
    )
    assert result.exit_code == 0, result.stdout
    state = json.loads(result.stdout)
    assert state["protocol_version"] == "1.0" and state["jobs"][0]["contact_id"] == PIPE
