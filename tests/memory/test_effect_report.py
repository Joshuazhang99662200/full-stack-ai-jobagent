"""Effect reports on fitted synthetic outcomes and through the real ledger and CLI."""

import json
from datetime import UTC, datetime, timedelta

from typer.testing import CliRunner

from jobagent.cli.app import app
from jobagent.memory.effect import memory_effect_report, sent_from_ledger
from jobagent.schemas.memory import ReplyOutcome
from jobagent.schemas.outreach import OutreachAudit, OutreachResult
from jobagent.storage.database import Database
from jobagent.storage.outreach_repository import SqliteOutreachRepository
from tests.bridge.test_greeting_context import populated

NOW = datetime(2026, 11, 20, tzinfo=UTC)


def outcomes(count: int, replies: int, *, version: str | None, status_pending: int = 0):
    rows = []
    for index in range(count):
        status = (
            "pending" if index < status_pending
            else "replied" if index < status_pending + replies
            else "no_reply"
        )
        rows.append(ReplyOutcome(
            batch_id="OBATCH_FIT", number=index + 1, job_id=f"JOB_FIT_{index}", platform="boss",
            sent_at=NOW - timedelta(days=30), memory_version=version,
            preference_rule_ids=["RULE_A"] if version else [], status=status,
        ))
    return rows


def test_fitted_data_with_a_real_lift_is_reported_higher_and_pending_is_excluded():
    data = [
        *outcomes(310, 90, version="PMEM_V2", status_pending=10),  # 90 / 300 = 30%
        *outcomes(300, 45, version=None),                          # 45 / 300 = 15%
    ]
    report = memory_effect_report(
        "CAND_TEST", data, window=timedelta(days=7), min_sample=30, observed_at=NOW
    )
    assert report.pending == 10
    by_label = {group.label: group.comparison for group in report.groups}
    version = by_label["PMEM_V2"]
    assert (version.treated_replies, version.treated_sent) == (90, 300)
    assert (version.baseline_replies, version.baseline_sent) == (45, 300)
    assert version.verdict == "higher" and version.interval_low is not None
    assert version.interval_low > 0
    assert by_label["PMEM_V2:RULE_A"].verdict == "higher"
    assert report.assignment == "observational" and report.grants_approval is False


def test_fitted_data_without_a_lift_makes_no_claim():
    data = [*outcomes(300, 60, version="PMEM_V2"), *outcomes(300, 57, version=None)]
    report = memory_effect_report(
        "CAND_TEST", data, window=timedelta(days=7), min_sample=30, observed_at=NOW
    )
    assert {g.comparison.verdict for g in report.groups} == {"no_clear_difference"}


def test_ledger_sends_link_to_replies_through_the_cli(tmp_path):
    path, job_id = populated(tmp_path, approved=True)
    store = SqliteOutreachRepository(Database(path))
    batch = store.get_batch("OBATCH_FIXTURE")
    approval = store.get_approval("OBATCH_FIXTURE")
    assert batch is not None and approval is not None
    store.append_audit(OutreachAudit(
        audit_id="OAUDIT_FIT_1", batch_id=batch.batch_id, number=1, job_id=job_id,
        platform=batch.items[0].platform, item_digest=batch.items[0].item_digest,
        approval_id=approval.approval_id, approval_channel=approval.channel,
        result=OutreachResult.SENT, recorded_at=NOW - timedelta(days=30),
    ))
    sent = sent_from_ledger(
        "CAND_TEST", batches=store.list_batches(), audits=store.list_audits(),
        owned_evidence_ids={"EVID_CURRENT"},
    )
    assert [(s.job_id, s.memory_version) for s in sent] == [(job_id, None)]
    assert sent_from_ledger(
        "CAND_OTHER", batches=store.list_batches(), audits=store.list_audits(),
        owned_evidence_ids={"EVID_FOREIGN"},
    ) == []

    result = CliRunner().invoke(app, [
        "memory", "effect", "--candidate", "CAND_TEST", "--window-days", "7",
        "--min-sample", "30", "--database", str(path),
    ])
    assert result.exit_code == 0, result.stdout
    report = json.loads(result.stdout)
    assert report["groups"] == [] and report["pending"] == 0
    assert report["assignment"] == "observational"


def test_cli_simulation_is_seeded_and_reproducible():
    args = [
        "memory", "simulate", "--trials", "200", "--sample-size", "100", "--base-rate", "0.2",
        "--lift", "0.1", "--min-sample", "30", "--seed", "5",
    ]
    first = CliRunner().invoke(app, args)
    second = CliRunner().invoke(app, args)
    assert first.exit_code == 0, first.stdout
    assert first.stdout == second.stdout
    assert 0 < json.loads(first.stdout)["detection_rate"] < 1
