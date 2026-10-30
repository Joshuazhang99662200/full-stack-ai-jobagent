"""Typed local worker handoffs; none of these contracts grants human approval."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, HttpUrl

from jobagent.schemas.applications import ApprovalChannel
from jobagent.schemas.common import ContractModel, Digest, NonEmptyString
from jobagent.schemas.job_intelligence import ObservationImportReport, SourceJobRecord
from jobagent.schemas.jobs import JobId
from jobagent.schemas.outreach import OutreachBatchId, OutreachItem, OutreachResult

WorkerId = Annotated[str, Field(pattern=r"^\S{1,128}$")]
WorkerTaskId = Annotated[str, Field(pattern=r"^W(?:FETCH|SEND)_[A-Z0-9_]{1,80}$")]
WorkerEventId = Annotated[str, Field(pattern=r"^WEVT_[A-Z0-9]{1,64}$")]
WorkerFetchStatus = Literal["stored", "rejected", "partial"]


class WorkerFetchRequest(ContractModel):
    task_id: Annotated[str, Field(pattern=r"^WFETCH_[A-Z0-9_]{1,80}$")]
    worker_id: WorkerId
    observations: list[SourceJobRecord] = Field(min_length=1, max_length=50)


class WorkerFetchReceipt(ContractModel):
    task_id: WorkerTaskId
    worker_id: WorkerId
    request_digest: Digest
    status: WorkerFetchStatus
    report: ObservationImportReport
    completed_at: AwareDatetime
    event_id: WorkerEventId


class WorkerSendClaim(ContractModel):
    task_id: WorkerTaskId
    worker_id: WorkerId
    batch_id: OutreachBatchId
    batch_digest: Digest
    policy_digest: Digest
    approval_id: NonEmptyString
    approval_channel: ApprovalChannel
    item: OutreachItem
    claimed_at: AwareDatetime
    state: Literal["claimed", "authorized"] = "claimed"


class WorkerReadback(ContractModel):
    task_id: WorkerTaskId
    worker_id: WorkerId
    result: Literal["sent", "duplicate_found", "failed", "intervention", "unknown"]
    observed_url: HttpUrl | None = None
    observed_text: str | None = None
    reason: str | None = None


class WorkerSendReceipt(ContractModel):
    task_id: WorkerTaskId
    worker_id: WorkerId
    result: OutreachResult
    observed_result: Literal["sent", "duplicate_found", "failed", "intervention", "unknown"]
    audit_id: NonEmptyString
    event_id: WorkerEventId
    completed_at: AwareDatetime
    reason: str | None = None


class WorkerEvent(ContractModel):
    event_id: WorkerEventId
    task_id: WorkerTaskId
    kind: Literal["fetch_completed", "greeting_completed"]
    status: NonEmptyString
    job_ids: list[JobId]
    created_at: AwareDatetime


class WorkerEventAck(ContractModel):
    event_id: WorkerEventId
    acknowledged: Literal[True] = True
