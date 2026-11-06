"""Muse panel decisions reach the existing approval gate and feedback memory, host-neutrally."""

import json
from datetime import timedelta

import pytest
from typer.testing import CliRunner

from jobagent.bridge.panel_decisions import (
    panel_materials,
    panel_operation,
    record_panel_decision,
)
from jobagent.bridge.preference_memory import load_preference_events
from jobagent.cli.app import app
from jobagent.schemas.console_host import HostDecisionRequest
from jobagent.schemas.pipeline import PipelineMeta
from jobagent.storage.database import Database
from jobagent.storage.outreach_repository import SqliteOutreachRepository
from jobagent.storage.pipeline_repository import PipelineRepository
from tests.bridge.test_greeting_context import NOW, populated
from tests.jobs.test_pipeline_contracts import row

TEXT = "Hello, I built research agents. Can we talk?"
PIPE = "PIPE_00000000000000A1"
LATER = NOW + timedelta(minutes=5)


def setup(tmp_path):
    path, job_id = populated(tmp_path, approved=False, source="boss")
    job = row(pipeline_id=PIPE, candidate_id="CAND_TEST", job_id="fixture-role")
    meta = PipelineMeta(
        pipeline_id=PIPE, normalized_job_id=job_id, entered_evidence_reference="ENTRY"
    )
    PipelineRepository(Database(path)).create(
        job, meta, event_id="PANEL_ENTRY", evidence_reference="ENTRY"
    )
    return path, job_id


def decision(path, kind="decline", *, body=TEXT, key="OP_1", revision=None, **changes):
    if revision is None:
        revision = panel_materials(path, "CAND_TEST", PIPE)[0].revision
    data = dict(
        candidate_id="CAND_TEST", job_id="fixture-role", contact_id=PIPE, operation_key=key,
        kind=kind, material_revision=revision, body=body, attachment_digests=[],
        note="不考虑纯工具岗",
    )
    data.update(changes)
    return HostDecisionRequest.model_validate(data)


def record(path, request):
    return record_panel_decision(path, request, actor_id="OWNER_SYNTHETIC", now=LATER)


def test_materials_offer_the_exact_asked_greeting_for_the_contact(tmp_path):
    path, _ = setup(tmp_path)
    [material] = panel_materials(path, "CAND_TEST", PIPE)
    batch = SqliteOutreachRepository(Database(path)).get_batch("OBATCH_FIXTURE")
    assert batch is not None
    assert material.revision == batch.items[0].item_digest and material.body == TEXT
    assert panel_materials(path, "CAND_OTHER", PIPE) == []


def test_decline_is_stored_as_feedback_and_closes_the_item_without_approval(tmp_path):
    path, job_id = setup(tmp_path)
    receipt = record(path, decision(path))

    assert receipt.status == "saved" and receipt.event_id
    events = load_preference_events(path, "CAND_TEST")
    assert [(e.action, e.job_id, e.free_text) for e in events] == [
        ("decline", job_id, "不考虑纯工具岗")
    ]
    store = SqliteOutreachRepository(Database(path))
    assert store.get_approval("OBATCH_FIXTURE") is None
    assert store.is_withdrawn("OBATCH_FIXTURE")
    assert panel_materials(path, "CAND_TEST", PIPE) == []


def test_approval_goes_through_the_gate_on_the_exact_asked_text(tmp_path):
    path, _ = setup(tmp_path)
    receipt = record(path, decision(path, "approve_text"))

    assert receipt.status == "saved"
    store = SqliteOutreachRepository(Database(path))
    child = [b for b in store.list_batches() if b.batch_id != "OBATCH_FIXTURE"]
    assert len(child) == 1 and child[0].items[0].text == TEXT
    approval = store.get_approval(child[0].batch_id)
    assert approval is not None and approval.approved_numbers == [1]
    assert approval.channel.value == "agent_relay"
    assert "Muse" in approval.attestation and TEXT in approval.attestation
    assert "OWNER_SYNTHETIC" in approval.attestation
    assert [e.action for e in load_preference_events(path, "CAND_TEST")] == ["approve"]


def test_edited_text_is_never_approved_directly(tmp_path):
    path, _ = setup(tmp_path)
    receipt = record(path, decision(path, "approve_text", body="Edited words."))
    assert receipt.status == "rejected"
    assert SqliteOutreachRepository(Database(path)).list_batches()[-1].batch_id == "OBATCH_FIXTURE"


def test_saved_edit_is_a_revision_request_not_an_approval(tmp_path):
    path, _ = setup(tmp_path)
    revised = "Hello, I evaluate grounded research agents. Shall we talk?"
    receipt = record(path, decision(path, "save_draft", body=revised))

    assert receipt.status == "saved"
    [event] = load_preference_events(path, "CAND_TEST")
    assert event.action == "revise" and event.revised_text == revised
    assert SqliteOutreachRepository(Database(path)).get_approval("OBATCH_FIXTURE") is None


@pytest.mark.parametrize(
    "changes",
    [
        {"revision": "sha256:" + "0" * 64},
        {"candidate_id": "CAND_OTHER"},
        {"contact_id": "PIPE_00000000000000B2"},
        {"job_id": "another-role"},
        {"kind": "answer_todo"},
        {"attachment_digests": ["sha256:" + "1" * 64]},
    ],
)
def test_stale_foreign_or_unsupported_decisions_are_rejected(tmp_path, changes):
    path, _ = setup(tmp_path)
    receipt = record(path, decision(path, **changes))
    assert receipt.status == "rejected" and receipt.event_id is None
    assert load_preference_events(path, "CAND_TEST") == []


def test_replays_return_the_same_receipt_and_operations_read_back(tmp_path):
    path, _ = setup(tmp_path)
    request = decision(path)
    first = record(path, request)
    again = record(path, request)
    assert (again.status, again.event_id) == ("saved", first.event_id)
    assert panel_operation(path, "CAND_TEST", "OP_1").event_id == first.event_id
    assert panel_operation(path, "CAND_TEST", "OP_UNSEEN").status == "rejected"
    conflicting = record(
        path, decision(path, "approve_text", key="OP_2", revision=request.material_revision)
    )
    assert conflicting.status == "rejected"


def test_cli_round_trip_for_a_host_adapter(tmp_path):
    path, _ = setup(tmp_path)
    materials = CliRunner().invoke(app, [
        "console", "materials", "--candidate", "CAND_TEST", "--contact", PIPE,
        "--database", str(path),
    ])
    assert materials.exit_code == 0, materials.stdout
    revision = json.loads(materials.stdout)[0]["revision"]
    request_path = tmp_path / "decision.json"
    request_path.write_text(decision(path, revision=revision).model_dump_json(), encoding="utf-8")

    decided = CliRunner().invoke(app, [
        "console", "decide", str(request_path), "--actor", "OWNER_SYNTHETIC",
        "--database", str(path),
    ])
    assert decided.exit_code == 0, decided.stdout
    assert json.loads(decided.stdout)["status"] == "saved"
    readback = CliRunner().invoke(app, [
        "console", "operation", "OP_1", "--candidate", "CAND_TEST", "--database", str(path),
    ])
    assert json.loads(readback.stdout)["event_id"] == json.loads(decided.stdout)["event_id"]


def two_item_list(tmp_path):
    from jobagent.jobs.normalization import JobNormalizer
    from jobagent.outreach.service import OutreachService
    from jobagent.schemas.job_intelligence import SourceJobRecord
    from jobagent.schemas.outreach import OutreachDraft
    from jobagent.storage.job_repository import SqliteJobRepository

    path, first_job = setup(tmp_path)
    db = Database(path)
    second = JobNormalizer().normalize(SourceJobRecord(
        source="boss", source_job_id="second-role", company="Second Labs",
        title="Evaluation Product", location="Shanghai",
        jd_raw="Own evaluation of grounded research answers.",
        url="https://careers.second-company.org/role", collected_at=NOW,
    ))
    jobs = SqliteJobRepository(db)
    jobs.save_job(second)
    service = OutreachService()
    report = service.build_batch(
        [OutreachDraft(job_id=job_id, platform="boss", text=TEXT, evidence_ids=["EVID_CURRENT"])
         for job_id in (first_job, second.id)],
        jobs={first_job: jobs.get_job(first_job), second.id: second}, already_contacted=set(),
        confirmed_evidence_ids={"EVID_CURRENT"}, batch_id="OBATCH_TWO", created_at=NOW,
    )
    assert report.batch is not None, report.rejected
    store = SqliteOutreachRepository(db)
    store.withdraw("OBATCH_FIXTURE", "replaced by a two-item list", NOW)
    store.save_batch(report.batch)
    ask = service.ask(report.batch, asked_at=NOW + timedelta(minutes=1))
    store.save_ask(ask)
    return path, ask.ask_id


def test_batch_approval_cannot_reapprove_items_already_decided_in_the_panel(tmp_path):
    path, ask_id = two_item_list(tmp_path)
    assert record(path, decision(path, "decline")).status == "saved"
    store = SqliteOutreachRepository(Database(path))
    assert not store.is_withdrawn("OBATCH_TWO")

    def approve(items):
        return CliRunner().invoke(app, [
            "outreach", "approve", "OBATCH_TWO", "--request", ask_id, "--items", items,
            "--answer", "发第 1 条", "--database", str(path),
        ])

    refused = approve("1")
    assert refused.exit_code == 1 and "already decided" in refused.stdout
    allowed = approve("2")
    assert allowed.exit_code == 0, allowed.stdout
