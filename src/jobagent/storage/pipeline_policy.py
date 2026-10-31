"""Read the authoritative rule head under the same transaction as production writes."""

import sqlite3
from datetime import UTC, datetime

from pydantic import ValidationError

from jobagent.errors import ContractValidationError
from jobagent.rules.pipeline_policy import check_pipeline_policy
from jobagent.rules.service import validate_snapshot
from jobagent.schemas.dynamic_rules import DynamicRuleSet
from jobagent.schemas.pipeline_policy import PipelinePolicyCheck, PipelinePolicyConsumer


def current_rule_snapshot(
    connection: sqlite3.Connection,
    candidate_id: str,
) -> DynamicRuleSet | None:
    """No head means legacy; a broken or foreign head must never look like legacy."""
    try:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='dynamic_rule_heads'",
        ).fetchone()
        if table is None:
            return None
        row = connection.execute(
            "SELECT h.version, v.snapshot_json FROM dynamic_rule_heads h "
            "LEFT JOIN dynamic_rule_versions v ON v.version=h.version "
            "WHERE h.candidate_id=?",
            (candidate_id,),
        ).fetchone()
        if row is None:
            return None
        if row[1] is None:
            raise ContractValidationError("Authoritative dynamic rule head has no snapshot.")
        snapshot = validate_snapshot(DynamicRuleSet.model_validate_json(row[1]))
        if snapshot.version != row[0] or snapshot.candidate_id != candidate_id:
            raise ContractValidationError(
                "Authoritative dynamic rule head scope or digest differs.",
            )
        return snapshot
    except (sqlite3.Error, ValidationError, ContractValidationError) as error:
        raise ContractValidationError(
            "Cannot verify the authoritative dynamic rule head.",
            details={"status": "not_integrated", "candidate_id": candidate_id, "can_write": False},
        ) from error


def require_pipeline_policy(
    connection: sqlite3.Connection,
    candidate_id: str,
    consumer: PipelinePolicyConsumer,
    *,
    now: datetime | None = None,
    for_write: bool = True,
) -> PipelinePolicyCheck:
    """The write lock prevents a newer head arriving between this check and the write."""
    if for_write and not connection.in_transaction:
        connection.execute("BEGIN IMMEDIATE")
    snapshot = current_rule_snapshot(connection, candidate_id)
    check = check_pipeline_policy(snapshot, candidate_id, consumer, now=now or datetime.now(UTC))
    if not check.can_write:
        raise ContractValidationError(
            "Pipeline dynamic policy is not integrated; affected writes are blocked.",
            details=check.model_dump(mode="json"),
        )
    return check
