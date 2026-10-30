"""Explicit opt-in bindings. Source ceilings and human permissions remain separate."""

import json
from decimal import Decimal

from jobagent.errors import ContractValidationError
from jobagent.rules.evaluation import required
from jobagent.rules.service import validate_snapshot
from jobagent.schemas.common import MoneyRange
from jobagent.schemas.dynamic_rules import DynamicRuleSet
from jobagent.schemas.job_intelligence import CandidateFilterContext


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
            "compensation_compare_mode": values["SALARY_COMPARE_MODE"],
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
