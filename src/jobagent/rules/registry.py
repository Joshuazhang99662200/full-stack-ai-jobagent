"""Named parameter types and governance. Definitions contain no personal defaults."""

import math
import re
from datetime import time
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import JsonValue

from jobagent.errors import ContractValidationError
from jobagent.schemas.dynamic_rules import RuleChangeRequest, RuleDefinition

_RUNTIME = {
    "POLL_INTERVAL_HOURS": "positive_number",
    "POLL_ALIGN_MINUTE": "local_time",
    "POLL_TIMEZONE": "timezone",
    "WEEKEND_PAUSE_START": "weekly_time",
    "WEEKEND_PAUSE_END": "weekly_time",
    "SALARY_FLOOR_K": "positive_number",
    "SALARY_COMPARE_MODE": "compensation_mode",
    "ABANDON_HOURS": "positive_number",
    "ABANDON_IMMEDIATE_REASONS": "abandon_reasons",
    "RESUME_STAGE_IN_ABANDON_LINE": "boolean",
    "PENDING_BACKLOG_ASK_THRESHOLD": "positive_integer",
    "DETAIL_CAP_PER_DAY": "positive_integer",
    "QUERIES_PER_SITE_PER_ROUND": "count_range",
    "JD_POINTS_MAX": "positive_integer",
    "GREETING_LEN_SHORT": "count_range",
    "GREETING_LEN_STANDARD": "count_range",
    "GREETING_LEN_EXPANDED": "count_range",
    "TECH_NOUN_BUDGET": "count_range",
    "GREETING_STRUCTURE": "greeting_structure",
}
_HOST = {
    "FIRST_LAUNCH_MIN_JD": "positive_integer",
    "FIRST_LAUNCH_MAX_JD": "positive_integer",
    "BOSS_SEND_INTERVAL_SEC": "count_range",
    "LIEPIN_DELIVERY_SPACING_SEC": "positive_number",
    "TOP_PER_QUERY": "positive_integer",
    "DETAIL_ATTEMPTS_PER_SITE_PER_ROUND": "positive_integer",
    "LIEPIN_CALLS_PER_ROUND": "positive_integer",
    "MCP_TOTAL": "positive_integer",
    "MCP_BATCHSIZE": "positive_integer",
    "MCP_MAX_PARALLEL": "positive_integer",
    "PANEL_ATTACH_TRIGGER": "after_poll_report",
    "PANEL_SYNC_ON_OPEN": "boolean",
    "PANEL_SYNC_MANUAL": "boolean",
    "PANEL_DAILY_SYNC_TIME": "local_time",
}
_INVARIANTS = {
    "ABANDON_WRITES",
    "RATIO_BASE",
    "GATE_POINT_MODE",
    "PHRASE_LIBRARY_RULE",
    "LIEPIN_DELIVERY_PARALLEL",
    "FEEDBACK_CONSUME_TIMING",
}
_PLATFORM = {"LIEPIN_API_RATE_PER_MIN", "LIEPIN_TOKEN_VALIDITY_DAYS"}


def definitions() -> list[RuleDefinition]:
    groups: tuple[tuple[Literal["runtime", "host"], dict[str, str]], ...] = (
        ("runtime", _RUNTIME),
        ("host", _HOST),
    )
    result = [
        RuleDefinition(
            name=name,
            category="user_parameter",
            binding=binding,
            value_type=kind,
            description=(
                "Explicit owner parameter; platform and approval constraints still apply."
            ),
            consumer=_consumer(name) if binding == "runtime" else "Host protocol only; no executor",
        )
        for binding, values in groups
        for name, kind in values.items()
    ]
    result.append(
        RuleDefinition(
            name="RATIO_TRIGGER_FACTOR",
            category="user_parameter",
            binding="proposal_only",
            value_type="ratio",
            description="Diagnostic proposals only; never activates optimization.",
            consumer="rules evaluate ratio (proposal only)",
        )
    )
    result.extend(
        RuleDefinition(
            name=name,
            category="invariant",
            binding="reference_only",
            value_type="fixed_boundary",
            description="Governance boundary; not an ordinary tuning variable.",
        )
        for name in _INVARIANTS
    )
    result.extend(
        RuleDefinition(
            name=name,
            category="platform_reference",
            binding="reference_only",
            value_type="reference",
            description=("Requires current platform evidence; "
                         "user tuning cannot change platform facts."),
        )
        for name in _PLATFORM
    )
    return sorted(result, key=lambda item: item.name)


def _consumer(name: str) -> str:
    if name.startswith(("POLL_", "WEEKEND_")):
        return "rules evaluate poll (no scheduler)"
    if name.startswith(("ABANDON_", "RESUME_STAGE_")):
        return "rules evaluate abandonment (no queue writes)"
    if name.startswith("SALARY_"):
        return "jobs filter/triage/pipeline --rules-file"
    if name == "DETAIL_CAP_PER_DAY":
        return "jobs sourcing-budget/reserve-read --rules-file (source ceiling remains)"
    if name == "QUERIES_PER_SITE_PER_ROUND":
        return "jobs search-plan --rules-file"
    if name == "PENDING_BACKLOG_ASK_THRESHOLD":
        return "rules evaluate backlog (user choice only)"
    return "greetings generate --rules-file (writing guidance, not content approval)"


def _number(value: JsonValue, *, integer: bool = False) -> bool:
    return (
        type(value) is int
        if integer
        else (
            type(value) in {int, float} and math.isfinite(float(value))  # type: ignore[arg-type]
        )
    )


def _range(value: JsonValue, *, positive: bool = False) -> bool:
    if type(value) is int:
        return value >= (1 if positive else 0)
    if not isinstance(value, list) or len(value) != 2:
        return False
    lower, upper = value
    return (type(lower) is int and type(upper) is int
            and lower >= (1 if positive else 0) and upper >= lower)


def _local_time(value: JsonValue) -> bool:
    if not isinstance(value, str) or re.fullmatch(r"\d{2}:\d{2}", value) is None:
        return False
    try:
        time.fromisoformat(value)
        return True
    except ValueError:
        return False


def validate_value(name: str, value: JsonValue) -> None:
    definition = next((item for item in definitions() if item.name == name), None)
    if definition is None:
        raise ContractValidationError("Unknown dynamic variable.", details={"name": name})
    if definition.category != "user_parameter":
        raise ContractValidationError(
            "This entry is a reference/invariant, not user tuning.",
            details={"name": name, "category": definition.category},
        )
    kind = definition.value_type
    valid = False
    if kind in {"positive_number", "positive_integer", "ratio"}:
        valid = _number(value, integer=kind == "positive_integer") and float(value) > 0  # type: ignore[arg-type]
        if kind == "ratio":
            valid = valid and float(value) <= 1  # type: ignore[arg-type]
    elif kind == "count_range":
        valid = _range(
            value, positive=name in {"QUERIES_PER_SITE_PER_ROUND", "BOSS_SEND_INTERVAL_SEC"}
        )
    elif kind == "boolean":
        valid = type(value) is bool
    elif kind == "local_time":
        valid = _local_time(value)
    elif kind == "weekly_time":
        valid = (
            isinstance(value, dict)
            and set(value) == {"weekday", "time"}
            and type(value["weekday"]) is int
            and 0 <= value["weekday"] <= 6
            and _local_time(value["time"])
        )
    elif kind == "timezone" and isinstance(value, str):
        try:
            ZoneInfo(value)
            valid = True
        except (ValueError, ZoneInfoNotFoundError):
            valid = False
    elif kind == "compensation_mode":
        valid = value in {"upper_bound", "lower_bound"} if isinstance(value, str) else False
    elif kind == "after_poll_report":
        valid = value == "after_poll_report"
    elif kind == "abandon_reasons":
        valid = (
            isinstance(value, list)
            and bool(value)
            and all(
                isinstance(item, str)
                and item
                in {
                    "employer_rejected",
                    "job_closed",
                    "user_abandoned",
                }
                for item in value
            )
            and len(set(value)) == len(value)
        )
    elif kind == "greeting_structure":
        valid = (
            isinstance(value, dict)
            and set(value)
            == {
                "main_narratives",
                "related_scenarios",
                "hard_results",
            }
            and all(_range(item) for item in value.values())
        )
    if not valid:
        raise ContractValidationError(
            "Invalid dynamic variable value/type/unit.", details={"name": name, "expected": kind}
        )


def validate_change(request: RuleChangeRequest) -> None:
    if request.provenance.source_kind != "user":
        raise ContractValidationError("Only explicit user decisions may activate user parameters.")
    validate_value(request.name, request.value)


def validate_values(values: dict[str, JsonValue]) -> None:
    for name, value in values.items():
        validate_value(name, value)
    low, high = values.get("FIRST_LAUNCH_MIN_JD"), values.get("FIRST_LAUNCH_MAX_JD")
    if low is not None and high is not None and int(low) > int(high):  # type: ignore[arg-type]
        raise ContractValidationError("First-launch minimum exceeds maximum.")
