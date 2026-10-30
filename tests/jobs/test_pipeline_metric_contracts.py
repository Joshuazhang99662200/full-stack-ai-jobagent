from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

START = datetime(2026, 1, 2, tzinfo=UTC)
END = START + timedelta(days=1)


def scope():
    return dict(
        dimension_platform="boss",
        dimension_domain="design",
        dimension_scenario="brand",
        dimension_tech="Figma",
        dimension_greeting_version="greeting-v1",
        dimension_resume_version=None,
        dimension_salary_band="18-25k",
    )


def metric(**changes):
    from jobagent.schemas.pipeline_metrics import PipelineStageMetric

    data = dict(
        metric_id="METRIC_SYNTHETIC_WINDOW",
        window_start=START,
        window_end=END,
        **scope(),
        stage_from="greeting_sent",
        stage_to="greeting_read",
        numerator=1,
        denominator=2,
        historical_rate=Decimal("0.8"),
        sliced_cumulative_rate=Decimal("0.5"),
        optimized_rate=None,
        window_rate=Decimal("0"),
        sample_count=2,
        diagnosis_id=None,
    )
    data.update(changes)
    return PipelineStageMetric.model_validate(data)


def test_metric_has_exact_storage_contract_fields():
    from jobagent.schemas.pipeline_metrics import PipelineStageMetric

    assert set(PipelineStageMetric.model_fields) - {"schema_version"} == set(
        [
            "metric_id",
            "window_start",
            "window_end",
            "dimension_platform",
            "dimension_domain",
            "dimension_scenario",
            "dimension_tech",
            "dimension_greeting_version",
            "dimension_resume_version",
            "dimension_salary_band",
            "stage_from",
            "stage_to",
            "numerator",
            "denominator",
            "historical_rate",
            "sliced_cumulative_rate",
            "optimized_rate",
            "window_rate",
            "sample_count",
            "diagnosis_id",
        ]
    )
    assert metric().sliced_cumulative_rate == Decimal("0.5")


@pytest.mark.parametrize(
    "changes",
    [
        dict(window_end=START),
        dict(window_start=START.replace(tzinfo=None)),
        dict(numerator=3),
        dict(sample_count=3),
        dict(sliced_cumulative_rate=Decimal("0.3")),
        dict(historical_rate=Decimal("1.1")),
        dict(stage_to="abandoned"),
        dict(stage_from="draft_pending", stage_to="interviewed"),
        dict(dimension_salary_band="custom salary slice"),
    ],
)
def test_metric_rejects_invalid_windows_rates_counts_or_funnel(changes):
    with pytest.raises(ValidationError):
        metric(**changes)


def test_zero_denominator_is_unknown_and_not_a_zero_rate():
    value = metric(
        numerator=0, denominator=0, sample_count=0, sliced_cumulative_rate=None, window_rate=None
    )
    assert value.sliced_cumulative_rate is None
    with pytest.raises(ValidationError):
        metric(
            numerator=0,
            denominator=0,
            sample_count=0,
            sliced_cumulative_rate=Decimal("0"),
            window_rate=None,
        )


def test_no_absolute_sample_gate_and_all_distinct_segments_are_declared():
    from jobagent.schemas.pipeline_metrics import PIPELINE_FUNNEL_SEGMENTS

    assert (
        metric(
            numerator=0, denominator=1, sample_count=1, sliced_cumulative_rate=Decimal("0")
        ).denominator
        == 1
    )
    assert len(PIPELINE_FUNNEL_SEGMENTS) == 9
    assert ("greeting_sent", "initial_contact") in PIPELINE_FUNNEL_SEGMENTS
    assert ("greeting_sent", "interviewed") in PIPELINE_FUNNEL_SEGMENTS
    assert ("resume_sent", "interview_pending") in PIPELINE_FUNNEL_SEGMENTS


def test_aware_windows_are_serialized_in_utc():
    value = metric(
        window_start=START.astimezone(__import__("datetime").timezone(timedelta(hours=8)))
    )
    assert value.window_start.utcoffset() == timedelta(0)


def diagnosis(**changes):
    from jobagent.schemas.pipeline_metrics import PipelineDiagnosis

    data = dict(
        diagnosis_id="DIAG_SYNTHETIC",
        candidate_id="CAND_DEMO",
        metric_id="METRIC_SYNTHETIC_WINDOW",
        window_start=START,
        window_end=END,
        **scope(),
        stage_from="greeting_sent",
        stage_to="greeting_read",
        historical_rate=Decimal("0.8"),
        sliced_cumulative_rate=Decimal("0.5"),
        optimized_rate=None,
        numerator=1,
        denominator=2,
        excluded_counts=dict(
            job_closed=0,
            employer_rejected=0,
            hard_filter=0,
            proof_pending=0,
            direct_invite_cancelled=0,
            interview_cancelled=0,
        ),
        diagnosis_code="funnel_blocked_at_read",
        evidence_references=["PRIVATE_METRIC_EVIDENCE"],
        source_digest="sha256:synthetic",
        rule_id=None,
        pre_rule_cumulative_rate=None,
    )
    data.update(changes)
    return PipelineDiagnosis.model_validate(data)


def test_diagnosis_requires_all_rates_exclusions_and_evidence():
    assert diagnosis().optimized_rate is None
    for key in (
        "historical_rate",
        "sliced_cumulative_rate",
        "optimized_rate",
        "excluded_counts",
        "evidence_references",
        "window_end",
        "source_digest",
    ):
        data = diagnosis().model_dump()
        data.pop(key)
        from jobagent.schemas.pipeline_metrics import PipelineDiagnosis

        with pytest.raises(ValidationError):
            PipelineDiagnosis.model_validate(data)


@pytest.mark.parametrize(
    "code",
    [
        "greeting_issue",
        "resume_issue",
        "funnel_blocked_at_read",
        "optimization_effective",
        "optimization_ineffective",
    ],
)
def test_five_fixed_diagnosis_codes_are_supported(code):
    changes = dict(diagnosis_code=code)
    if code.startswith("optimization_"):
        changes.update(
            rule_id="CONFIRMED_RULE",
            optimized_rate=Decimal("0.9"),
            pre_rule_cumulative_rate=Decimal("0.5"),
        )
    assert diagnosis(**changes).diagnosis_code == code


def test_unknown_diagnosis_or_partial_exclusion_map_is_rejected():
    with pytest.raises(ValidationError):
        diagnosis(diagnosis_code="guess_bad_cv")
    with pytest.raises(ValidationError):
        diagnosis(excluded_counts={"job_closed": 0})
    with pytest.raises(ValidationError):
        diagnosis(evidence_references=[])
