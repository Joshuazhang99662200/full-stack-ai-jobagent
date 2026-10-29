from datetime import timedelta
from decimal import Decimal

import pytest

from tests.jobs.test_pipeline_metric_contracts import END, START, scope


def fact(number, *, sent_at=None, read_at=None, job_id=None, **changes):
    from jobagent.schemas.pipeline_metrics import PipelineMetricFact

    entered = START - timedelta(days=1)
    times = {"draft_pending": entered}
    if sent_at is not None:
        times["greeting_sent"] = sent_at
    if read_at is not None:
        times["greeting_read"] = read_at
    data = dict(
        **scope(),
        pipeline_id=f"PIPE_FACT_{number}",
        candidate_id="CAND_DEMO",
        job_id=job_id or f"boss-job-{number}",
        stage_times=times,
        proof_verified=True,
        exclusion_reason=None,
        evidence_references=[f"PROOF_{number}"],
    )
    data.update(changes)
    return PipelineMetricFact.model_validate(data)


def request(**changes):
    from jobagent.schemas.pipeline_metrics import PipelineMetricRequest

    return PipelineMetricRequest.model_validate(
        dict(candidate_id="CAND_DEMO", window_start=START, window_end=END, scope=scope(), **changes)
    )


def compute(facts, **changes):
    from jobagent.jobs.pipeline_metrics import compute_metrics

    return compute_metrics(request(**changes), facts, now=END)


def selected(result, source="greeting_sent", target="greeting_read"):
    return next(m for m in result.metrics if (m.stage_from, m.stage_to) == (source, target))


def evidence_for(result, metric):
    return next(e for e in result.evidence if e.metric_id == metric.metric_id)


def test_compute_separates_historical_cumulative_window_and_optimized_cohorts():
    from jobagent.schemas.pipeline_metrics import ConfirmedPipelineMetricRule

    old = START - timedelta(hours=12)
    rows = [
        fact(i, sent_at=old, read_at=old + timedelta(minutes=1) if i < 4 else None)
        for i in range(8)
    ]
    rows += [fact(i, sent_at=START + timedelta(hours=1)) for i in range(8, 10)]
    rule = ConfirmedPipelineMetricRule.model_validate(
        dict(
            rule_id="RULE_CONFIRMED",
            candidate_id="CAND_DEMO",
            scope=scope(),
            stage_from="greeting_sent",
            stage_to="greeting_read",
            confirmed_at=START,
            effective_at=START,
            pre_rule_cumulative_rate=Decimal("0.5"),
            owner_confirmation_reference="OWNER_CONFIRMATION",
        )
    )
    result = compute(rows, rule=rule)
    metric = selected(result)
    assert metric.historical_rate == Decimal("0.5")
    assert metric.sliced_cumulative_rate == Decimal("0.4")
    assert metric.window_rate == Decimal("0") and metric.optimized_rate == Decimal("0")
    assert (metric.numerator, metric.denominator, metric.sample_count) == (4, 10, 10)
    evidence = evidence_for(result, metric)
    assert evidence.historical_counts.model_dump(exclude={"schema_version"}) == {
        "numerator": 4,
        "denominator": 8,
    }
    assert evidence.window_counts.denominator == 2 and evidence.optimized_counts.denominator == 2
    assert len(result.metrics) == len(result.evidence) == 9


def test_abandoned_jobs_remain_in_denominator_and_exclusion_causes_are_visible():
    old = START - timedelta(hours=1)
    row = fact(1, sent_at=old, exclusion_reason="job_closed")
    row.stage_times["abandoned"] = START + timedelta(hours=1)
    result = compute([row])
    metric = selected(result)
    assert (metric.numerator, metric.denominator) == (0, 1)
    assert evidence_for(result, metric).excluded_counts.job_closed == 1
    assert evidence_for(result, metric).exclusion_job_ids["job_closed"] == [row.job_id]


def test_pending_proof_never_counts_as_verified_sent_but_entry_is_retained():
    rows = [
        fact(1, sent_at=START, proof_verified=False, exclusion_reason="proof_pending"),
        fact(2, sent_at=START),
    ]
    result = compute(rows)
    sent = selected(result)
    entry = selected(result, "draft_pending", "greeting_sent")
    assert sent.denominator == 1
    assert (entry.numerator, entry.denominator) == (1, 2)
    assert evidence_for(result, sent).excluded_counts.proof_pending == 1


def test_same_job_recontact_cannot_borrow_new_round_conversion_or_inflate_denominator():
    first = fact(1, job_id="boss-same", sent_at=START - timedelta(hours=1))
    later = fact(
        2,
        job_id="boss-same",
        sent_at=START + timedelta(hours=1),
        read_at=START + timedelta(hours=2),
    )
    result = compute([later, first, first])
    metric = selected(result)
    assert (metric.numerator, metric.denominator) == (0, 1)
    assert compute([first, later]) == result


def test_state_evidence_must_be_from_same_round_and_not_future_or_reverse_order():
    from jobagent.errors import ContractValidationError

    with pytest.raises(ContractValidationError):
        compute([fact(1, sent_at=START, read_at=START - timedelta(minutes=1))])
    with pytest.raises(ContractValidationError):
        compute([fact(1, sent_at=END + timedelta(seconds=1))])


def test_cutoffs_do_not_include_conversion_that_only_happened_in_later_window():
    old = START - timedelta(hours=1)
    row = fact(1, sent_at=old, read_at=START + timedelta(hours=1))
    result = compute([row])
    metric = selected(result)
    assert metric.historical_rate == Decimal("0")
    assert metric.sliced_cumulative_rate == Decimal("1")
    assert metric.window_rate is None


def test_window_end_is_exclusive_and_future_window_is_rejected():
    from jobagent.errors import ContractValidationError
    from jobagent.jobs.pipeline_metrics import compute_metrics

    result = compute([fact(1, sent_at=END)])
    assert selected(result).denominator == 0
    with pytest.raises(ContractValidationError):
        compute_metrics(request(), [], now=START)
    with pytest.raises(ContractValidationError):
        compute_metrics(request(), [], now=END.replace(tzinfo=None))


def test_candidate_and_exact_feature_version_slice_isolation_and_all_platform_aggregation():
    from jobagent.jobs.pipeline_metrics import compute_metrics
    from jobagent.schemas.pipeline_metrics import PipelineMetricRequest

    good = fact(1, sent_at=START)
    rows = [
        good,
        fact(2, sent_at=START, candidate_id="CAND_OTHER"),
        fact(3, sent_at=START, dimension_domain="other"),
        fact(4, sent_at=START, dimension_greeting_version="other-version"),
        fact(5, sent_at=START, dimension_platform="zhaopin"),
    ]
    assert selected(compute(rows)).denominator == 1
    all_scope = {**scope(), "dimension_platform": "all"}
    all_request = PipelineMetricRequest(
        candidate_id="CAND_DEMO", window_start=START, window_end=END, scope=all_scope
    )
    assert selected(compute_metrics(all_request, rows, now=END)).denominator == 2


def test_conflicting_immutable_pipeline_facts_are_rejected_not_silently_overwritten():
    from jobagent.errors import ContractValidationError

    old = fact(1, sent_at=START)
    changed = old.model_copy(update={"proof_verified": False})
    with pytest.raises(ContractValidationError):
        compute([old, changed])


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, None),
        (0, "below18k"),
        (17, "below18k"),
        (18, "18-25k"),
        (24, "18-25k"),
        (25, "25-40k"),
        (39, "25-40k"),
        (40, "40k+"),
    ],
)
def test_fixed_salary_buckets_do_not_change_candidate_filter_rules(value, expected):
    from jobagent.jobs.pipeline_metrics import salary_band

    assert salary_band(value) == expected


def test_unsent_draft_is_not_misreported_as_a_pending_send_proof():
    result = compute([fact(1, proof_verified=False)])
    assert selected(result, "draft_pending", "greeting_sent").denominator == 1
    assert all(item.excluded_counts.proof_pending == 0 for item in result.evidence)
