import pytest

from jobagent.errors import ContractValidationError
from jobagent.schemas.sourcing import SourcingRunRequest
from tests.rules.test_evaluation import profile


def sourcing_rules(**changes):
    return profile(
        {
            "QUERIES_PER_SITE_PER_ROUND": 2,
            "TOP_PER_QUERY": 3,
            "DETAIL_ATTEMPTS_PER_SITE_PER_ROUND": 4,
            "DETAIL_CAP_PER_DAY": 9,
        }
        | changes
    )


def test_confirmed_quantities_fill_omitted_values_without_reconfirmation():
    from jobagent.rules.bindings import bind_sourcing_run

    rules = sourcing_rules()
    intent = SourcingRunRequest(run_id="RUN_SYNTH", candidate_id=rules.candidate_id, source="boss")
    frozen = bind_sourcing_run(rules, intent, source_ceiling=50)
    assert (frozen.query_limit, frozen.top_per_query, frozen.detail_limit) == (2, 3, 4)
    assert frozen.daily_detail_cap == 9 and frozen.rules_version == rules.version
    assert frozen.budget_profile == "conservative"
    assert intent.detail_limit == 20


@pytest.mark.parametrize(
    "field,value",
    [
        ("query_limit", 3),
        ("detail_limit", 5),
        ("daily_detail_cap", 8),
        ("top_per_query", 2),
    ],
)
def test_explicit_conflicting_quantity_is_rejected_not_clamped(field, value):
    from jobagent.rules.bindings import bind_sourcing_run

    rules = sourcing_rules()
    request = SourcingRunRequest.model_validate(
        {
            "run_id": "RUN_SYNTH",
            "candidate_id": rules.candidate_id,
            "source": "boss",
            field: value,
        }
    )
    with pytest.raises(ContractValidationError, match=r"conflict"):
        bind_sourcing_run(rules, request, source_ceiling=50)


def test_missing_scope_missing_value_and_source_conflict_block_without_new_defaults():
    from jobagent.rules.bindings import bind_sourcing_run

    rules = sourcing_rules()
    request = SourcingRunRequest(run_id="RUN_SYNTH", candidate_id="CAND_OTHER", source="boss")
    with pytest.raises(ContractValidationError, match=r"candidate"):
        bind_sourcing_run(rules, request, source_ceiling=50)
    request = request.model_copy(update={"candidate_id": rules.candidate_id})
    with pytest.raises(ContractValidationError, match=r"ceiling"):
        bind_sourcing_run(rules, request, source_ceiling=5)
    incomplete = profile({"TOP_PER_QUERY": 3})
    with pytest.raises(ContractValidationError) as failure:
        bind_sourcing_run(incomplete, request, source_ceiling=50)
    assert "DETAIL_ATTEMPTS_PER_SITE_PER_ROUND" in failure.value.details["missing"]


def test_large_values_do_not_implicitly_select_expanded_policy():
    from jobagent.rules.bindings import bind_sourcing_run

    rules = sourcing_rules(QUERIES_PER_SITE_PER_ROUND=8, DETAIL_CAP_PER_DAY=120)
    request = SourcingRunRequest(run_id="RUN_SYNTH", candidate_id=rules.candidate_id, source="boss")
    with pytest.raises(ContractValidationError, match=r"policy|ceiling"):
        bind_sourcing_run(rules, request, source_ceiling=50)


def test_explicit_expanded_policy_keeps_confirmed_values_and_version():
    from jobagent.rules.bindings import bind_sourcing_run

    rules = sourcing_rules(QUERIES_PER_SITE_PER_ROUND=8, DETAIL_CAP_PER_DAY=120)
    request = SourcingRunRequest(
        run_id="RUN_SYNTH",
        candidate_id=rules.candidate_id,
        source="boss",
        budget_profile="muse-expanded-v1",
        rules_version=rules.version,
    )
    frozen = bind_sourcing_run(rules, request, source_ceiling=50)
    assert frozen.daily_detail_cap == 120 and frozen.detail_limit == 4
    assert frozen.budget_profile == "muse-expanded-v1" and frozen.query_limit == 8
