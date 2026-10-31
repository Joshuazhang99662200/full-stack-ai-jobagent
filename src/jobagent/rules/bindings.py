"""Explicit opt-in bindings. Source ceilings and human permissions remain separate."""

import json
from decimal import Decimal

from jobagent.errors import ContractValidationError
from jobagent.rules.evaluation import required
from jobagent.rules.service import validate_snapshot
from jobagent.schemas.common import MoneyRange
from jobagent.schemas.dynamic_rules import DynamicRuleSet
from jobagent.schemas.job_intelligence import CandidateFilterContext
from jobagent.schemas.sourcing import SourcingRunRequest


def bind_filter_context(
    rules: DynamicRuleSet,
    context: CandidateFilterContext,
) -> CandidateFilterContext:
    values = required(rules, ["SALARY_FLOOR_K", "SALARY_COMPARE_MODE"])
    if context.candidate_id != rules.candidate_id:
        raise ContractValidationError("Dynamic rules belong to another candidate.")
    if context.minimum_compensation is None or context.minimum_compensation.period is None:
        raise ContractValidationError(
            "Salary binding needs explicit currency and period in context."
        )
    return CandidateFilterContext.model_validate(
        {
            **context.model_dump(),
            "minimum_compensation": MoneyRange(
                currency=context.minimum_compensation.currency,
                period=context.minimum_compensation.period,
                minimum=Decimal(str(values["SALARY_FLOOR_K"])) * Decimal(1000),
            ),
            "unstated_compensation_passes": False,
            "compensation_comparison": values["SALARY_COMPARE_MODE"],
        }
    )


def bind_read_cap(rules: DynamicRuleSet, *, source_ceiling: int) -> int:
    values = required(rules, ["DETAIL_CAP_PER_DAY"])
    cap = int(values["DETAIL_CAP_PER_DAY"])  # type: ignore[arg-type]
    if cap > source_ceiling:
        raise ContractValidationError(
            "Dynamic read cap exceeds the current source ceiling.",
            details={"requested": cap, "source_ceiling": source_ceiling},
        )
    return cap


def bind_query_count(rules: DynamicRuleSet, *, explicit: int | None = None) -> int:
    values = required(rules, ["QUERIES_PER_SITE_PER_ROUND"])
    value = values["QUERIES_PER_SITE_PER_ROUND"]
    count = int(value[0] if isinstance(value, list) else value)  # type: ignore[arg-type]
    if explicit is not None and explicit != count:
        raise ContractValidationError("Explicit query count conflicts with dynamic rules.")
    return count


def bind_sourcing_run(
    rules: DynamicRuleSet, request: SourcingRunRequest, *, source_ceiling: int,
) -> SourcingRunRequest:
    values = required(rules, [
        "QUERIES_PER_SITE_PER_ROUND", "TOP_PER_QUERY",
        "DETAIL_ATTEMPTS_PER_SITE_PER_ROUND", "DETAIL_CAP_PER_DAY",
    ])
    if request.candidate_id != rules.candidate_id:
        raise ContractValidationError("Sourcing rules belong to another candidate.")
    if request.rules_version is not None and request.rules_version != rules.version:
        raise ContractValidationError("Sourcing rule version conflicts with the current snapshot.")
    expected = {
        "query_limit": bind_query_count(rules),
        "top_per_query": values["TOP_PER_QUERY"],
        "detail_limit": values["DETAIL_ATTEMPTS_PER_SITE_PER_ROUND"],
        "daily_detail_cap": values["DETAIL_CAP_PER_DAY"],
    }
    for field, value in expected.items():
        if field in request.model_fields_set and getattr(request, field) != value:
            raise ContractValidationError(
                "Explicit sourcing quantity conflicts with confirmed configuration.",
                details={"field": field},
            )
    cap = int(values["DETAIL_CAP_PER_DAY"])  # type: ignore[arg-type]
    if request.budget_profile == "conservative" and cap > source_ceiling:
        raise ContractValidationError("Confirmed daily cap exceeds the current source ceiling.")
    top = int(values["TOP_PER_QUERY"])  # type: ignore[arg-type]
    if request.budget_profile == "muse-expanded-v1" and top > 10:
        raise ContractValidationError("Confirmed result count conflicts with the expanded policy.")
    try:
        return SourcingRunRequest.model_validate({
            **request.model_dump(include=set(SourcingRunRequest.model_fields)),
            **expected, "rules_version": rules.version,
        })
    except ValueError as error:
        raise ContractValidationError(
            "Confirmed quantities conflict with the selected policy.",
        ) from error


def greeting_guidance(rules: DynamicRuleSet) -> list[str]:
    validate_snapshot(rules)
    names = [
        "GREETING_LEN_SHORT",
        "GREETING_LEN_STANDARD",
        "GREETING_LEN_EXPANDED",
        "TECH_NOUN_BUDGET",
        "GREETING_STRUCTURE",
        "JD_POINTS_MAX",
    ]
    selected = {name: rules.values[name] for name in names if name in rules.values}
    if not selected:
        raise ContractValidationError("Dynamic profile contains no greeting preferences.")
    return [
        f"Dynamic rule version {rules.version}; explicit experimental writing preferences: "
        + json.dumps(selected, sort_keys=True, ensure_ascii=False)
        + ". Preferences do not confirm facts, performance claims, approval or platform limits.",
    ]
