"""Synthetic persisted integration; internal verified fixtures are never live host proof."""

from datetime import timedelta
from decimal import Decimal

import pytest
from typer.testing import CliRunner

from jobagent.cli.app import app
from jobagent.errors import ContractValidationError
from jobagent.storage.message_diff_repository import MessageDiffRepository
from jobagent.storage.pipeline_metrics import PipelineMetricsService
from jobagent.storage.pipeline_rules import PipelineRuleService
from tests.storage.test_job_intake_service import NOW
from tests.storage.test_pipeline_metrics import compute_input, prepared, transition


def cohort(tmp_path, number, day, *, read):
    at = NOW + timedelta(days=day, hours=1)
    service, pair = prepared(tmp_path, number=number, at=at)
    pair = transition(service, pair, "greeting_sent", at=at + timedelta(seconds=1), number=number)
    if read:
        pair = transition(
            service, pair, "greeting_read", at=at + timedelta(seconds=2), number=number
        )
        pair = transition(
            service, pair, "initial_contact", at=at + timedelta(seconds=3), number=number
        )
    return service, pair


def persistent_read_block(tmp_path):
    pipeline, pair = cohort(tmp_path, 1, 0, read=True)
    for number, day, read in [
        (2, 1, False),
        (3, 1, False),
        (4, 1, True),
        (5, 2, False),
        (6, 2, False),
    ]:
        pipeline, pair = cohort(tmp_path, number, day, read=read)
    metrics = PipelineMetricsService(pipeline.database)
    end = NOW + timedelta(days=3)
    previous = metrics.compute(
        compute_input(pair, start=NOW + timedelta(days=1), end=NOW + timedelta(days=2)), now=end
    )
    current = metrics.compute(compute_input(pair, start=NOW + timedelta(days=2), end=end), now=end)
    report = metrics.diagnose(
        dict(
            candidate_id="CAND_DEMO",
            current_metric_ids=[m["metric_id"] for m in current["metrics"]],
            previous_metric_ids=[m["metric_id"] for m in previous["metrics"]],
        ),
        now=end,
    )
    assert [d["diagnosis_code"] for d in report["diagnoses"]] == ["funnel_blocked_at_read"]
    diagnosis = metrics.get_diagnosis(report["diagnoses"][0]["diagnosis_id"], "CAND_DEMO")
    assert diagnosis.sliced_cumulative_rate == Decimal(1) / 3
    return pipeline, pair, metrics, diagnosis, end


def propose(service, diagnosis, *, now):
    return service.propose(
        dict(
            proposal_id="SYNTHETIC_SCOPED_RULE",
            candidate_id="CAND_DEMO",
            diagnosis_id=diagnosis.diagnosis_id,
            diagnosis_digest=diagnosis.source_digest,
            category="style",
            rule_text_after="Use a direct, evidence-grounded opening.",
        ),
        now=now,
    )


def owner_decision(proposal, *, confirmation_id="SYNTHETIC_OWNER_CONFIRMATION"):
    return dict(
        confirmation_id=confirmation_id,
        proposal_id=proposal["proposal_id"],
        candidate_id="CAND_DEMO",
        rule_hash=proposal["rule_hash"],
        accepted=True,
        owner_text="I confirm this exact scoped rule.",
        owner_reference="PRIVATE_OWNER_REPLY",
    )


@pytest.mark.parametrize("read_after_rule", [False, True])
def test_persisted_metrics_to_owner_rule_and_optimization_review(tmp_path, read_after_rule):
    pipeline, pair, metrics, diagnosis, end = persistent_read_block(tmp_path)
    rules = PipelineRuleService(pipeline.database)
    proposal = propose(rules, diagnosis, now=end)
    shared = MessageDiffRepository(pipeline.database)
    assert shared.confirmed_rules("CAND_DEMO") == []
    with pytest.raises(ContractValidationError):
        rules.metric_rule(proposal["proposal_id"], "CAND_DEMO")
    confirmation = owner_decision(proposal)
    rules.confirm(confirmation, now=end)
    actual = rules.metric_rule(proposal["proposal_id"], "CAND_DEMO")
    assert actual.effective_at == end and actual.pre_rule_cumulative_rate == Decimal(1) / 3
    assert shared.confirmed_rules("CAND_DEMO")[0]["source_kind"] == "pipeline_diagnosis"
    assert shared.confirmed_rules("CAND_OTHER") == []
    # The existing host facade consumes the same candidate-scoped confirmed-rule ledger.
    cli = CliRunner().invoke(
        app, ["host", "confirmed-rules", "CAND_DEMO", "--database", str(pipeline.database.path)]
    )
    assert cli.exit_code == 0, cli.output
    assert proposal["proposal_id"] in cli.stdout

    for number in (7, 8):
        pipeline, pair = cohort(tmp_path, number, 3, read=read_after_rule)
    after = NOW + timedelta(days=4)
    request = {**compute_input(pair, start=end, end=after), "rule_id": proposal["proposal_id"]}
    optimized = metrics.compute(request, now=after)
    post_report = metrics.diagnose(
        dict(
            candidate_id="CAND_DEMO",
            current_metric_ids=[m["metric_id"] for m in optimized["metrics"]],
            rule_id=proposal["proposal_id"],
        ),
        now=after,
    )
    expected = "optimization_effective" if read_after_rule else "optimization_ineffective"
    assert [item["diagnosis_code"] for item in post_report["diagnoses"]] == [expected]
    post = post_report["diagnoses"][0]
    review = rules.review(
        dict(
            review_id="SYNTHETIC_REVIEW",
            candidate_id="CAND_DEMO",
            rule_id=proposal["proposal_id"],
            diagnosis_id=post["diagnosis_id"],
            diagnosis_digest=post["source_digest"],
        ),
        now=after,
    )
    assert review["outcome"] == expected and review["rules_changed"] is False
    assert len(shared.confirmed_rules("CAND_DEMO")) == 1
    if read_after_rule:
        assert review["rollback_proposal"] is None
    else:
        rollback = review["rollback_proposal"]
        assert rollback["operation"] == "withdraw"
        assert rules.metric_rule(proposal["proposal_id"], "CAND_DEMO") == actual
        rules.confirm(
            owner_decision(rollback, confirmation_id="SYNTHETIC_OWNER_ROLLBACK"), now=after
        )
        assert shared.confirmed_rules("CAND_DEMO") == []
        with pytest.raises(ContractValidationError):
            rules.metric_rule(proposal["proposal_id"], "CAND_DEMO")


def test_real_persisted_fact_backfill_stales_an_unconfirmed_rule_proposal(tmp_path):
    pipeline, _pair, metrics, diagnosis, end = persistent_read_block(tmp_path)
    rules = PipelineRuleService(pipeline.database)
    proposal = propose(rules, diagnosis, now=end)
    before = metrics.get_evidence(diagnosis.metric_id, "CAND_DEMO")
    # A newly recovered historical source job genuinely changes this closed window's cohort.
    cohort(tmp_path, 7, 2, read=False)
    fresh = metrics.fresh_evidence(diagnosis.metric_id, "CAND_DEMO", now=end)
    assert before.source_digest != fresh.source_digest
    assert fresh.cumulative_counts.denominator > before.cumulative_counts.denominator
    with pytest.raises(ContractValidationError, match="Metric facts changed"):
        rules.confirm(owner_decision(proposal), now=end)
    assert MessageDiffRepository(pipeline.database).confirmed_rules("CAND_DEMO") == []
    with pipeline.database.connect() as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM message_rule_confirmations").fetchone()[0] == 0
        )
