from datetime import timedelta
from decimal import Decimal

import pytest

from tests.jobs.test_pipeline_metric_contracts import END, START, metric, scope


def request(
    *,
    low=(),
    window_rate=Decimal("1"),
    scale=1,
    previous_low=True,
    exclusions=None,
    reviewed=False,
    optimized=None,
    rule=None,
):
    from jobagent.schemas.pipeline_metrics import (
        PipelineDiagnosisRequest,
        PipelineExclusionCounts,
        PipelineMetricEvidence,
        PipelineRateCounts,
    )

    segments = [
        ("greeting_sent", "greeting_read"),
        ("greeting_read", "initial_contact"),
        ("greeting_sent", "initial_contact"),
        ("resume_sent", "interview_pending"),
    ]
    current, previous, evidence = [], [], []
    empty = dict(
        job_closed=0,
        employer_rejected=0,
        hard_filter=0,
        proof_pending=0,
        direct_invite_cancelled=0,
        interview_cancelled=0,
    )
    causes = {**empty, **(exclusions or {})}
    for index, segment in enumerate(segments):
        current_rate = Decimal("0.5") if segment in low else Decimal("0.7")
        opt = optimized if rule and segment == (rule.stage_from, rule.stage_to) else None
        item = metric(
            metric_id=f"METRIC_CURRENT_{index}",
            stage_from=segment[0],
            stage_to=segment[1],
            numerator=int(current_rate * 20 * scale),
            denominator=20 * scale,
            sample_count=20 * scale,
            historical_rate=Decimal("0.7"),
            sliced_cumulative_rate=current_rate,
            window_rate=window_rate,
            optimized_rate=opt,
        )
        prior_rate = Decimal("0.7")
        prior = metric(
            metric_id=f"METRIC_PREVIOUS_{index}",
            stage_from=segment[0],
            stage_to=segment[1],
            window_start=START - timedelta(days=1),
            window_end=START,
            numerator=7 * scale,
            denominator=10 * scale,
            sample_count=10 * scale,
            historical_rate=Decimal("1") if previous_low else prior_rate,
            sliced_cumulative_rate=prior_rate,
            window_rate=prior_rate,
        )
        current.append(item)
        previous.append(prior)
        evidence.append(
            PipelineMetricEvidence(
                metric_id=item.metric_id,
                candidate_id="CAND_DEMO",
                historical_counts=PipelineRateCounts(numerator=7 * scale, denominator=10 * scale),
                cumulative_counts=PipelineRateCounts(
                    numerator=item.numerator, denominator=item.denominator
                ),
                optimized_counts=None
                if opt is None
                else PipelineRateCounts(numerator=int(opt * 10), denominator=10),
                window_counts=PipelineRateCounts(numerator=int(window_rate * 10), denominator=10),
                cohort_job_ids=[f"boss-synthetic-{index}-{i}" for i in range(item.denominator)],
                excluded_counts=PipelineExclusionCounts.model_validate(causes),
                exclusion_job_ids={
                    reason: [f"boss-synthetic-{index}-{i}" for i in range(count)]
                    for reason, count in causes.items()
                },
                evidence_references=["PRIVATE_WINDOW_LOG"],
                source_digest="sha256:synthetic-current",
            )
        )
    return PipelineDiagnosisRequest(
        candidate_id="CAND_DEMO",
        current=current,
        previous=previous,
        evidence=evidence,
        exclusions_reviewed=reviewed,
        rule=rule,
    )


def codes(result):
    return [item.diagnosis_code for item in result.diagnoses]


def diagnose(data):
    from jobagent.jobs.pipeline_diagnosis import diagnose

    return diagnose(data, now=END)


def confirmed_rule(**changes):
    from jobagent.schemas.pipeline_metrics import ConfirmedPipelineMetricRule

    data = dict(
        rule_id="RULE_CONFIRMED",
        candidate_id="CAND_DEMO",
        scope=scope(),
        stage_from="greeting_sent",
        stage_to="greeting_read",
        confirmed_at=START,
        effective_at=START,
        pre_rule_cumulative_rate=Decimal("0.6"),
        owner_confirmation_reference="PRIVATE_OWNER_CONFIRMATION",
    )
    data.update(changes)
    return ConfirmedPipelineMetricRule.model_validate(data)


def test_greeting_issue_needs_persistent_cumulative_drop_and_healthy_resume_segment():
    data = request(low=[("greeting_read", "initial_contact")])
    result = diagnose(data)
    assert codes(result) == ["greeting_issue"]
    item = result.diagnoses[0]
    assert item.stage_from == "greeting_read" and item.stage_to == "initial_contact"
    assert item.historical_rate == Decimal("0.7") and item.sliced_cumulative_rate == Decimal("0.5")
    assert item.evidence_references and item.source_digest


def test_low_read_rate_with_healthy_post_read_reply_is_blocked_not_greeting_copy_issue():
    data = request(low=[("greeting_sent", "greeting_read")])
    assert codes(diagnose(data)) == ["funnel_blocked_at_read"]


def test_resume_issue_requires_normal_greeting_total_conversion():
    data = request(low=[("resume_sent", "interview_pending")])
    assert codes(diagnose(data)) == ["resume_issue"]
    data = request(low=[("resume_sent", "interview_pending"), ("greeting_sent", "initial_contact")])
    result = diagnose(data)
    assert "resume_issue" not in codes(result)
    assert result.observation_reasons


def test_single_window_or_non_contiguous_history_cannot_establish_persistent_deterioration():
    data = request(low=[("greeting_read", "initial_contact")], previous_low=False)
    assert diagnose(data).diagnoses == []
    assert diagnose(data).observation_reasons
    no_history = data.model_copy(update={"previous": []})
    assert diagnose(no_history).diagnoses == []
    older = [
        value.model_copy(
            update={
                "window_start": START - timedelta(days=3),
                "window_end": START - timedelta(days=2),
            }
        )
        for value in data.previous
    ]
    assert diagnose(data.model_copy(update={"previous": older})).diagnoses == []


def test_window_rate_alone_never_triggers_diagnosis_and_absolute_counts_do_not_change_it():
    assert diagnose(request(window_rate=Decimal("0"))).diagnoses == []
    small = diagnose(request(low=[("greeting_read", "initial_contact")], scale=1))
    large = diagnose(request(low=[("greeting_read", "initial_contact")], scale=1000))
    assert codes(small) == codes(large) == ["greeting_issue"]
    assert large.diagnoses[0].denominator > small.diagnoses[0].denominator


def test_all_companion_segment_rates_and_complete_evidence_are_required():
    data = request(low=[("greeting_read", "initial_contact")])
    without_resume = data.model_copy(update={"current": data.current[:-1]})
    result = diagnose(without_resume)
    assert result.diagnoses == [] and result.observation_reasons
    without_evidence = data.model_copy(update={"evidence": data.evidence[:-1]})
    from jobagent.errors import ContractValidationError

    with pytest.raises(ContractValidationError):
        diagnose(without_evidence)


def test_unreviewed_confounding_causes_require_observation_instead_of_attribution():
    low = [("greeting_read", "initial_contact")]
    data = request(low=low, exclusions={"job_closed": 1, "employer_rejected": 1})
    result = diagnose(data)
    assert result.diagnoses == [] and result.observation_reasons
    reviewed = diagnose(request(low=low, exclusions={"job_closed": 1}, reviewed=True))
    assert codes(reviewed) == ["greeting_issue"]
    assert reviewed.diagnoses[0].excluded_counts.job_closed == 1


@pytest.mark.parametrize(
    "opt, expected",
    [
        (Decimal("0.9"), "optimization_effective"),
        (Decimal("0.7"), "optimization_ineffective"),
        (Decimal("0.6"), "optimization_ineffective"),
    ],
)
def test_optimization_review_requires_better_than_both_cumulative_baselines(opt, expected):
    rule = confirmed_rule()
    result = diagnose(request(rule=rule, optimized=opt))
    assert codes(result) == [expected]
    assert result.diagnoses[0].rule_id == rule.rule_id
    assert result.diagnoses[0].pre_rule_cumulative_rate == rule.pre_rule_cumulative_rate
    assert result.diagnoses[0].optimized_rate == opt


def test_optimization_can_fail_pre_rule_baseline_even_if_it_beats_history():
    rule = confirmed_rule(pre_rule_cumulative_rate=Decimal("0.9"))
    result = diagnose(request(rule=rule, optimized=Decimal("0.8")))
    assert codes(result) == ["optimization_ineffective"]


def test_no_optimized_cohort_is_unknown_and_never_a_rollback_decision():
    result = diagnose(request(rule=confirmed_rule(), optimized=None))
    assert result.diagnoses == [] and result.observation_reasons


def test_cumulative_evidence_cannot_be_substituted_for_a_different_candidate_or_counts():
    from jobagent.errors import ContractValidationError

    data = request(low=[("greeting_read", "initial_contact")])
    wrong = [e.model_copy(update={"candidate_id": "CAND_OTHER"}) for e in data.evidence]
    with pytest.raises(ContractValidationError):
        diagnose(data.model_copy(update={"evidence": wrong}))
    wrong = [
        e.model_copy(update={"source_digest": "sha256:changed"}) if i == 0 else e
        for i, e in enumerate(data.evidence)
    ]
    with pytest.raises(ContractValidationError):
        diagnose(data.model_copy(update={"evidence": wrong}))


def test_threshold_equality_does_not_count_as_strict_deterioration():
    data = request(low=[("greeting_read", "initial_contact")])
    index = 1
    current = data.current[index].model_copy(
        update={
            "numerator": 14,
            "denominator": 25,
            "sample_count": 25,
            "sliced_cumulative_rate": Decimal("0.56"),
        }
    )
    evidence = data.evidence[index].model_copy(
        update={
            "cohort_job_ids": [f"boss-threshold-{i}" for i in range(25)],
            "cumulative_counts": __import__(
                "jobagent.schemas.pipeline_metrics", fromlist=["PipelineRateCounts"]
            ).PipelineRateCounts(numerator=14, denominator=25),
        }
    )
    values, proofs = list(data.current), list(data.evidence)
    values[index], proofs[index] = current, evidence
    result = diagnose(data.model_copy(update={"current": values, "evidence": proofs}))
    assert result.diagnoses == []
