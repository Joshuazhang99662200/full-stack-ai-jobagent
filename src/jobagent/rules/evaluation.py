"""Evaluate explicit variables without scheduling, sending or rewriting queue history."""

import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import JsonValue

from jobagent.errors import ContractValidationError
from jobagent.rules.service import validate_snapshot
from jobagent.schemas.dynamic_rules import DynamicRuleSet
from jobagent.schemas.rule_evaluation import (
    AbandonmentEvaluation,
    AbandonmentObservation,
    BacklogEvaluation,
    PollEvaluation,
    RatioEvaluation,
    RatioObservation,
)


def required(rules: DynamicRuleSet, names: list[str]) -> dict[str, JsonValue]:
    validate_snapshot(rules)
    missing = [name for name in names if name not in rules.values]
    if missing:
        raise ContractValidationError(
            "Dynamic rule consumer requires explicit variables.", details={"missing": missing}
        )
    return {name: rules.values[name] for name in names}


def _aware(moment: datetime) -> None:
    if moment.tzinfo is None:
        raise ContractValidationError("Evaluation time requires a timezone offset.")


def _weekly(value: JsonValue) -> int:
    assert isinstance(value, dict)
    hour, minute = str(value["time"]).split(":")
    return int(value["weekday"]) * 1440 + int(hour) * 60 + int(minute)  # type: ignore[arg-type]


def evaluate_poll(
    rules: DynamicRuleSet,
    now: datetime,
    *,
    last_check_at: datetime | None = None,
) -> PollEvaluation:
    names = [
        "POLL_INTERVAL_HOURS",
        "POLL_ALIGN_MINUTE",
        "POLL_TIMEZONE",
        "WEEKEND_PAUSE_START",
        "WEEKEND_PAUSE_END",
    ]
    values = required(rules, names)
    _aware(now)
    if last_check_at is not None:
        _aware(last_check_at)
        if last_check_at > now:
            raise ContractValidationError("Last patrol check is in the future.")
    zone = ZoneInfo(str(values["POLL_TIMEZONE"]))
    local = now.astimezone(zone)
    hours, minutes = str(values["POLL_ALIGN_MINUTE"]).split(":")
    origin = datetime(1970, 1, 5, int(hours), int(minutes), tzinfo=zone)
    seconds = float(values["POLL_INTERVAL_HOURS"]) * 3600  # type: ignore[arg-type]
    if seconds < 1 or seconds > timedelta(days=7).total_seconds():
        raise ContractValidationError("Polling interval is outside the supported precision/window.")
    start, end = (_weekly(values[name]) for name in names[-2:])
    if start == end:
        raise ContractValidationError("Weekly pause endpoints must differ.")

    def paused(moment: datetime) -> bool:
        minute = moment.weekday() * 1440 + moment.hour * 60 + moment.minute
        return start <= minute < end if start < end else minute >= start or minute < end

    def ceiling(moment: datetime) -> datetime:
        slot = math.ceil((moment - origin).total_seconds() / seconds)
        return origin + timedelta(seconds=slot * seconds)

    next_slot = ceiling(local)
    slot_index = math.floor((local - origin).total_seconds() / seconds)
    latest = origin + timedelta(seconds=slot_index * seconds)
    active = not paused(local)
    due = active and not paused(latest) and (last_check_at is None or last_check_at < latest)
    if not due and next_slot == local:
        next_slot = ceiling(local + timedelta(microseconds=1))
    for _ in range(3):
        if not paused(next_slot):
            break
        current_minute = next_slot.weekday() * 1440 + next_slot.hour * 60 + next_slot.minute
        delta = (end - current_minute) % (7 * 1440)
        pause_end = next_slot.replace(second=0, microsecond=0) + timedelta(minutes=delta)
        next_slot = ceiling(pause_end)
    else:
        raise ContractValidationError("Polling cadence cannot reach an open weekly window.")
    if due:
        next_slot = local
    return PollEvaluation(
        rule_version=rules.version,
        referenced_variables=names,
        reason="aligned_due" if due else "weekly_pause" if not active else "next_aligned_slot",
        active=active,
        due=due,
        next_poll_at=next_slot,
        scheduled_slot_at=latest,
    )


def evaluate_abandonment(
    rules: DynamicRuleSet,
    observation: AbandonmentObservation,
    now: datetime,
) -> AbandonmentEvaluation:
    names = ["ABANDON_HOURS", "ABANDON_IMMEDIATE_REASONS", "RESUME_STAGE_IN_ABANDON_LINE"]
    values = required(rules, names)
    _aware(now)
    observation = AbandonmentObservation.model_validate(observation.model_dump(mode="json"))
    times = [
        time
        for time in (
            observation.sent_at,
            observation.read_at,
            observation.last_substantive_activity_at,
            observation.last_checked_at,
        )
        if time is not None
    ]
    if any(time > now for time in times):
        raise ContractValidationError("Workflow evidence timestamps are in the future.")
    reason = "awaiting_timeout"
    changed = False
    deadline = None
    if observation.terminal:
        reason = "terminal_history_unchanged"
    elif (
        observation.immediate_verified
        and observation.immediate_reason
        and observation.immediate_reason in values["ABANDON_IMMEDIATE_REASONS"]  # type: ignore[operator]
        and observation.last_evidence
    ):
        reason, changed = observation.immediate_reason, True
    elif observation.stage == "resume" and not values["RESUME_STAGE_IN_ABANDON_LINE"]:
        reason = "resume_stage_exempt"
    else:
        clock = [
            moment
            for moment in (
                observation.read_at or observation.sent_at,
                observation.last_substantive_activity_at,
            )
            if moment is not None
        ]
        if not clock or not observation.last_evidence:
            reason = "missing_confirmed_clock_or_evidence"
        else:
            deadline = max(clock) + timedelta(hours=float(values["ABANDON_HOURS"]))  # type: ignore[arg-type]
            if now >= deadline:
                reason = "read_no_reply_timeout" if observation.read_at else "no_reply_timeout"
                changed = True
    return AbandonmentEvaluation(
        rule_version=rules.version,
        referenced_variables=names,
        reason=reason,
        pipeline_id=observation.pipeline_id,
        changed=changed,
        abandoned=changed,
        abandoned_at=now if changed else None,
        deadline_at=deadline,
        last_evidence=observation.last_evidence,
        last_checked_at=now,
    )


def evaluate_ratio(rules: DynamicRuleSet, observation: RatioObservation) -> RatioEvaluation:
    values = required(rules, ["RATIO_TRIGGER_FACTOR"])
    observation = RatioObservation.model_validate(observation.model_dump(mode="json"))
    factor = float(values["RATIO_TRIGGER_FACTOR"])  # type: ignore[arg-type]
    propose = (
        observation.denominator > 0
        and observation.window_valid
        and observation.sustained
        and observation.sliced_cumulative_rate is not None
        and observation.historical_rate is not None
        and observation.sliced_cumulative_rate < observation.historical_rate * factor
    )
    return RatioEvaluation(
        rule_version=rules.version,
        referenced_variables=["RATIO_TRIGGER_FACTOR"],
        reason="diagnostic_proposal" if propose else "insufficient_or_non_triggering_slice",
        propose_diagnosis=propose,
        denominator=observation.denominator,
    )


def evaluate_backlog(rules: DynamicRuleSet, pending_review: int) -> BacklogEvaluation:
    values = required(rules, ["PENDING_BACKLOG_ASK_THRESHOLD"])
    if type(pending_review) is not int or pending_review < 0:
        raise ContractValidationError("Pending backlog must be a nonnegative integer.")
    needs_choice = pending_review > int(values["PENDING_BACKLOG_ASK_THRESHOLD"])  # type: ignore[arg-type]
    return BacklogEvaluation(
        rule_version=rules.version,
        referenced_variables=["PENDING_BACKLOG_ASK_THRESHOLD"],
        reason="ask_pause_or_review" if needs_choice else "within_backlog_threshold",
        needs_user_choice=needs_choice,
        pending_review=pending_review,
    )
