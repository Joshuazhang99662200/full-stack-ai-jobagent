"""Typed, non-persistent dynamic workflow decisions."""

from typing import Literal

from pydantic import AwareDatetime, Field

from jobagent.schemas.common import ContractModel, NonEmptyString


class RuleEvaluation(ContractModel):
    rule_version: NonEmptyString
    referenced_variables: list[str]
    reason: NonEmptyString
    persisted: Literal[False] = False
    snapshot_mode: Literal["unverified", "current", "historical"] = "unverified"
    current_head_verified: bool = False


class PollEvaluation(RuleEvaluation):
    active: bool
    due: bool
    next_poll_at: AwareDatetime
    scheduled_slot_at: AwareDatetime | None = None


class AbandonmentObservation(ContractModel):
    pipeline_id: NonEmptyString
    sent_at: AwareDatetime | None = None
    read_at: AwareDatetime | None = None
    last_substantive_activity_at: AwareDatetime | None = None
    stage: Literal["greeting", "conversation", "resume", "other"] = "greeting"
    terminal: bool = False
    immediate_reason: Literal["employer_rejected", "job_closed", "user_abandoned"] | None = None
    immediate_verified: bool = False
    last_evidence: str | None = None
    last_checked_at: AwareDatetime | None = None


class AbandonmentEvaluation(RuleEvaluation):
    pipeline_id: NonEmptyString
    changed: bool
    abandoned: bool
    abandoned_at: AwareDatetime | None = None
    deadline_at: AwareDatetime | None = None
    last_evidence: str | None = None
    last_checked_at: AwareDatetime | None = None
    retained_in_denominator: Literal[True] = True
    grants_recontact_permission: Literal[False] = False


class RatioObservation(ContractModel):
    sliced_cumulative_rate: float | None = Field(default=None, ge=0, le=1)
    historical_rate: float | None = Field(default=None, ge=0, le=1)
    optimized_rate: float | None = Field(default=None, ge=0, le=1)
    window_rate: float | None = Field(default=None, ge=0, le=1)
    denominator: int = Field(ge=0)
    sustained: bool
    window_valid: bool
    evidence_ref: NonEmptyString


class RatioEvaluation(RuleEvaluation):
    propose_diagnosis: bool
    proposal_only: Literal[True] = True
    denominator: int


class BacklogEvaluation(RuleEvaluation):
    needs_user_choice: bool
    pending_review: int
    discards_items: Literal[False] = False
