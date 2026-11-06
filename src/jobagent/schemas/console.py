"""Console transport reuses authoritative business contracts without redefining them."""

from typing import Literal

from pydantic import AwareDatetime, Field

from jobagent.schemas.candidate import CandidateId
from jobagent.schemas.common import ContractModel, NonEmptyString
from jobagent.schemas.harness import HarnessRun, RunId
from jobagent.schemas.jobs import HardFilterResult, MatchResult
from jobagent.schemas.pipeline import PipelineHistory, PipelineJob, PipelineMeta
from jobagent.schemas.public_careers import PublicCareerRecord, PublicCareerRun


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
    # The host's own declared plan; the console never infers a next step.
    next_step: str | None = None


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


class ConsolePublicCareers(ContractModel):
    """Read-only discovery data; no contact round or approval is synthesized."""

    status: Literal["complete", "missing", "invalid"] = "missing"
    records: list[PublicCareerRecord] = Field(default_factory=list)
    runs: list[PublicCareerRun] = Field(default_factory=list)


class ConsoleOutreachDecision(ContractModel):
    """One listed first greeting and what the person decided, read from the ledger.

    Projection only: it grants nothing, and items that cannot be tied to this
    candidate through confirmed evidence or a source binding are not shown.
    """

    batch_id: NonEmptyString
    ask_id: NonEmptyString | None
    number: int = Field(ge=1)
    job_id: NonEmptyString
    platform: NonEmptyString
    company: NonEmptyString
    title: NonEmptyString
    text: NonEmptyString
    item_digest: NonEmptyString
    asked_at: AwareDatetime | None
    state: Literal[
        "not_asked", "awaiting_answer", "approved", "not_selected", "revision_requested",
        "declined", "withdrawn",
    ]
    decided_via: Literal["batch_approval", "item_decision"] | None = None
    revised_text: str | None = None
    approval_id: NonEmptyString | None = None
    approved_at: AwareDatetime | None = None
    approval_attestation: str | None = None
    send_result: NonEmptyString | None = None
    sent_at: AwareDatetime | None = None


class ConsoleSnapshot(ContractModel):
    candidate_id: CandidateId
    generated_at: AwareDatetime
    sources: list[ConsoleSource] = Field(default_factory=list)
    jobs: list[ConsoleJob] = Field(default_factory=list)
    runs: list[ConsoleRun] = Field(default_factory=list)
    approvals: list[ConsoleOutreachDecision] = Field(default_factory=list)
    public_careers: ConsolePublicCareers = Field(default_factory=ConsolePublicCareers)
