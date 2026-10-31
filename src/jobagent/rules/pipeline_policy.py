"""Check configuration against production semantics without rewriting its history."""

from datetime import datetime

from pydantic import JsonValue

from jobagent.errors import ContractValidationError
from jobagent.jobs.pipeline import SILENCE_LIMIT
from jobagent.jobs.pipeline_diagnosis import DECLINE_FACTOR
from jobagent.rules.service import validate_snapshot
from jobagent.schemas.dynamic_rules import DynamicRuleSet
from jobagent.schemas.pipeline_policy import (
    PipelinePolicyCheck,
    PipelinePolicyConflict,
    PipelinePolicyConsumer,
)


def check_pipeline_policy(
    snapshot: DynamicRuleSet | None,
    candidate_id: str,
    consumer: PipelinePolicyConsumer,
    *,
    now: datetime,
) -> PipelinePolicyCheck:
    """Present values must match the fixed consumer; an active profile cannot omit them."""
    if now.tzinfo is None:
        raise ContractValidationError("Pipeline policy verification requires an aware time.")
    if snapshot is None:
        return PipelinePolicyCheck(
            candidate_id=candidate_id,
            consumer=consumer,
            status="legacy",
            can_write=True,
        )
    snapshot = validate_snapshot(snapshot)
    supported: dict[str, JsonValue] = (
        {
            "ABANDON_HOURS": SILENCE_LIMIT.total_seconds() / 3600,
            "ABANDON_IMMEDIATE_REASONS": ["employer_rejected", "job_closed", "user_abandoned"],
            "RESUME_STAGE_IN_ABANDON_LINE": True,
        }
        if consumer == "state"
        else {"RATIO_TRIGGER_FACTOR": float(DECLINE_FACTOR)}
    )
    conflicts = []
    if snapshot.candidate_id != candidate_id:
        conflicts.append(
            PipelinePolicyConflict(
                variable="candidate_id",
                reason="scope_mismatch",
                configured=snapshot.candidate_id,
                supported=candidate_id,
            )
        )
    if snapshot.effective_at > now:
        conflicts.append(
            PipelinePolicyConflict(
                variable="rules_version",
                reason="future_version",
                configured=snapshot.effective_at.isoformat(),
                supported=now.isoformat(),
            )
        )
    for name, expected in supported.items():
        if name not in snapshot.values:
            conflicts.append(
                PipelinePolicyConflict(
                    variable=name,
                    reason="missing_value",
                    supported=expected,
                )
            )
            continue
        actual = snapshot.values[name]
        matches = actual == expected
        if (
            name == "ABANDON_IMMEDIATE_REASONS"
            and isinstance(actual, list)
            and isinstance(expected, list)
        ):
            matches = sorted(str(item) for item in actual) == sorted(str(item) for item in expected)
        if not matches:
            conflicts.append(
                PipelinePolicyConflict(
                    variable=name,
                    reason="unsupported_value",
                    configured=actual,
                    supported=expected,
                )
            )
    return PipelinePolicyCheck(
        candidate_id=candidate_id,
        consumer=consumer,
        rules_version=snapshot.version,
        status="not_integrated" if conflicts else "compatible",
        can_write=not conflicts,
        referenced_variables=list(supported),
        conflicts=conflicts,
    )
