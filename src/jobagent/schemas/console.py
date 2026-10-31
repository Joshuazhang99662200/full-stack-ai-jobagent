"""Console transport reuses authoritative business contracts without redefining them."""

from typing import Literal

from pydantic import AwareDatetime, Field

from jobagent.schemas.candidate import CandidateId
from jobagent.schemas.common import ContractModel, NonEmptyString
from jobagent.schemas.harness import HarnessRun, RunId
from jobagent.schemas.jobs import HardFilterResult, MatchResult
from jobagent.schemas.pipeline import PipelineHistory, PipelineJob, PipelineMeta


class ConsoleSource(ContractModel):
    name: str
    status: Literal["complete", "missing", "invalid", "unsupported"]
    message: str | None = None


class ConsoleActivityInput(ContractModel):
    event_id: NonEmptyString
    run_id: RunId
    candidate_id: CandidateId
    activity_id: NonEmptyString
    activity: Literal[
        "fetch", "detail", "match", "draft_greeting", "review", "approval", "readback", "report"
    ]
    status: Literal["started", "heartbeat", "waiting", "completed", "failed"]
    occurred_at: AwareDatetime
    owner: NonEmptyString
    job_id: str | None = None
    evidence_reference: str | None = None
    artifact_reference: str | None = None
    checkpoint_reference: str | None = None
    message: str | None = None


class ConsoleActivity(ConsoleActivityInput):
    recorded_at: AwareDatetime


class ConsoleFilterContext(ContractModel):
    job_id: NonEmptyString
    updated_at: AwareDatetime
    policy_digest: NonEmptyString


class ConsoleMatchContext(ConsoleFilterContext):
    evidence_digest: NonEmptyString
    requirements_digest: NonEmptyString


class ConsoleJob(ContractModel):
    job: PipelineJob
    meta: PipelineMeta
    history: list[PipelineHistory]
    match_result: MatchResult | None = None
    match_context: ConsoleMatchContext | None = None
    hard_filter_result: HardFilterResult | None = None
    hard_filter_context: ConsoleFilterContext | None = None


class ConsoleRun(ContractModel):
    run: HarnessRun
    activities: list[ConsoleActivity]
    freshness: Literal["current", "stale", "terminal", "unknown"]


class ConsoleSnapshot(ContractModel):
    candidate_id: CandidateId
    generated_at: AwareDatetime
    sources: list[ConsoleSource] = Field(default_factory=list)
    jobs: list[ConsoleJob] = Field(default_factory=list)
    runs: list[ConsoleRun] = Field(default_factory=list)
    approvals: list[dict[str, object]] = Field(default_factory=list)
