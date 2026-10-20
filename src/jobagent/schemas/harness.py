"""Portable workflow state. A checkpoint never grants delivery authority."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from jobagent.schemas.candidate import CandidateId
from jobagent.schemas.common import ContractModel, Digest, NonEmptyString

RunId = Annotated[str, Field(pattern=r"^RUN_[A-F0-9]{32}$")]
Host = Literal["codex", "claude-code"]


class RunPhase(StrEnum):
    NEW = "new"
    RUNNING = "running"
    WAITING_FOR_FACT_CONFIRMATION = "waiting_for_fact_confirmation"
    WAITING_FOR_JOB_SELECTION = "waiting_for_job_selection"
    WAITING_FOR_REVIEW = "waiting_for_review"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    WAITING_FOR_LOGIN = "waiting_for_login"
    DELIVERY_OUTCOME_UNKNOWN = "delivery_outcome_unknown"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunArtifact(ContractModel):
    path: NonEmptyString
    contract: NonEmptyString
    digest: Digest


class HarnessRun(ContractModel):
    run_id: RunId
    candidate_id: CandidateId
    runtime_digest: Digest
    host: Host
    phase: RunPhase = RunPhase.NEW
    session_id: NonEmptyString | None = None
    lease_until: datetime | None = None
    created_at: datetime
    updated_at: datetime
    artifacts: list[RunArtifact] = Field(default_factory=list)


class ResumeHeader(ContractModel):
    """Identity lines the candidate supplies for the top of the page.

    Name, contact details and job intent are not claims about experience, so they
    carry no evidence. They are allowed only verbatim and only above the first item,
    and the report records their digest so the exemption stays visible.
    """

    lines: Annotated[list[NonEmptyString], Field(min_length=1)]


class PdfCheckReport(ContractModel):
    variant_id: NonEmptyString
    variant_digest: Digest
    pdf_digest: Digest
    page_count: Annotated[int, Field(ge=0)]
    passed: bool
    issues: list[str] = Field(default_factory=list)
    header_digest: Digest | None = None


class ApplicationOutcome(ContractModel):
    application_id: NonEmptyString
    job_id: NonEmptyString
    status: Literal["unknown", "simulated", "sent", "failed", "user_intervention_required"]
    attempts: Annotated[int, Field(ge=0)]


class HarnessReport(ContractModel):
    run_id: RunId
    outcomes: list[ApplicationOutcome] = Field(default_factory=list)
