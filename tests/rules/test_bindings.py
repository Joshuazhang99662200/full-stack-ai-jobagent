from decimal import Decimal

import pytest

from jobagent.errors import ContractValidationError
from jobagent.schemas.common import MoneyRange
from jobagent.schemas.job_intelligence import CandidateFilterContext
from tests.rules.test_evaluation import profile


def test_salary_binding_uses_explicit_scope_and_preserves_other_preferences():
    from jobagent.rules.bindings import bind_filter_context

    rules = profile({"SALARY_FLOOR_K": 27, "SALARY_COMPARE_MODE": "upper_bound"})
    context = CandidateFilterContext(
        candidate_id="CAND_SYNTHETIC",
        excluded_role_terms=["configured exclusion"],
        minimum_compensation=MoneyRange(currency="CNY", minimum=Decimal(1000), period="month"),
        unstated_compensation_passes=True,
    )
    updated = bind_filter_context(rules, context)
    assert updated.minimum_compensation.minimum == 27000
    assert not updated.unstated_compensation_passes
    assert context.minimum_compensation.minimum == 1000
    assert updated.excluded_role_terms == context.excluded_role_terms
    with pytest.raises(ContractValidationError, match="candidate"):
        bind_filter_context(rules, context.model_copy(update={"candidate_id": "CAND_OTHER"}))


def test_budget_conflict_and_explicit_query_mismatch_do_not_fall_back():
    from jobagent.rules.bindings import bind_query_count, bind_read_cap

    rules = profile({"DETAIL_CAP_PER_DAY": 80, "QUERIES_PER_SITE_PER_ROUND": [5, 7]})
    with pytest.raises(ContractValidationError, match="ceiling"):
        bind_read_cap(rules, source_ceiling=40)
    assert bind_query_count(rules) == 5
    with pytest.raises(ContractValidationError, match="conflict"):
        bind_query_count(rules, explicit=3)


def test_greeting_bindings_are_preferences_and_do_not_grant_permission():
    from jobagent.rules.bindings import greeting_guidance

    rules = profile({"GREETING_LEN_SHORT": [100, 170], "TECH_NOUN_BUDGET": [0, 1]})
    guidance = greeting_guidance(rules)
    assert "100" in " ".join(guidance)
    assert rules.version in " ".join(guidance)


def test_confirmed_salary_comparison_mode_changes_selected_bound():
    from datetime import UTC, datetime

    from jobagent.jobs.hard_filter import HardFilterEngine
    from jobagent.jobs.normalization import JobNormalizer
    from jobagent.rules.bindings import bind_filter_context
    from jobagent.schemas.job_intelligence import HardFilterPolicy, SourceJobRecord
    from jobagent.schemas.jobs import FilterDecision, JobRequirementProfile

    context = CandidateFilterContext(
        candidate_id="CAND_SYNTHETIC",
        minimum_compensation=MoneyRange(currency="CNY", minimum=Decimal(20000), period="month"),
    )
    job = JobNormalizer("CNY").normalize(
        SourceJobRecord(
            source="mock",
            source_job_id="synthetic",
            title="Researcher",
            company="Synthetic",
            location="Test",
            salary_text="20-30k",
            jd_raw="Synthetic research duties.",
            url="https://example.test/role",
            collected_at=datetime.now(UTC),
        )
    )
    rules = profile({"SALARY_FLOOR_K": 25, "SALARY_COMPARE_MODE": "lower_bound"})
    result = HardFilterEngine().evaluate(
        job,
        JobRequirementProfile(job_id=job.id),
        bind_filter_context(rules, context),
        HardFilterPolicy(),
    )
    assert result.decision == FilterDecision.REJECT
