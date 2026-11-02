"""Host transport only; these records never replace pipeline or approval services."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from jobagent.schemas.candidate import CandidateId
from jobagent.schemas.common import NonEmptyString


class HostModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HostAttachment(HostModel):
    name: NonEmptyString
    url: NonEmptyString
    digest: NonEmptyString


class HostMaterial(HostModel):
    revision: NonEmptyString
    label: NonEmptyString
    body: str
    attachments: list[HostAttachment]


class HostDecisionRequest(HostModel):
    candidate_id: CandidateId
    job_id: NonEmptyString
    contact_id: NonEmptyString
    operation_key: NonEmptyString
    kind: Literal["save_draft", "approve_text", "approve_material", "decline", "answer_todo"]
    material_revision: NonEmptyString
    body: str
    attachment_digests: list[str]
    note: str
    todo_id: str | None = None
    option_id: str | None = None


class HostReceipt(HostModel):
    operation_key: str
    status: Literal["saved", "unknown", "rejected"]
    message: str
    event_id: str | None = None


class HostEvent(HostModel):
    event_id: NonEmptyString
    operation_key: NonEmptyString
    job_id: NonEmptyString
    contact_id: NonEmptyString
    kind: str
    occurred_at: AwareDatetime
    detail: str
    material: HostMaterial | None


class HostOption(HostModel):
    option_id: NonEmptyString
    label: NonEmptyString
    consequence: NonEmptyString


class HostTodo(HostModel):
    todo_id: NonEmptyString
    job_id: NonEmptyString
    contact_id: NonEmptyString
    question: NonEmptyString
    material_revision: NonEmptyString
    requires_person: bool
    host_resolved: bool
    basis: list[str]
    options: list[HostOption]
    status: Literal["pending", "resolved"]
    result: str | None

    @model_validator(mode="after")
    def require_personal_basis(self) -> "HostTodo":
        if self.requires_person and self.host_resolved and (not self.basis or not self.options):
            raise ValueError("A personal decision needs a basis and named options")
        return self


class HostReadback(HostModel):
    status: Literal["verified", "failed", "unknown"]
    detail: str
    evidence: str | None = None
    material_revision: str | None = None
    observed_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def require_positive_evidence(self) -> "HostReadback":
        if self.status == "verified" and not (
            self.evidence and self.material_revision and self.observed_at
        ):
            raise ValueError("Verified execution requires material-bound positive readback")
        return self


class HostJob(HostModel):
    job_id: NonEmptyString
    contact_id: NonEmptyString
    materials: list[HostMaterial]
    events: list[HostEvent]
    blockers: list[str]
    progress: str | None
    intake_at: AwareDatetime | None


class HostExecutionItem(HostModel):
    item_id: NonEmptyString
    job_id: NonEmptyString
    contact_id: NonEmptyString
    title: str
    channel: str
    material: HostMaterial
    approval_event_id: NonEmptyString
    status: Literal["queued", "running", "verified", "failed", "unknown"]
    readback: HostReadback | None
    selected: bool = False


class HostExcluded(HostModel):
    job_id: str
    reason: str


class HostBatch(HostModel):
    batch_id: NonEmptyString
    status: Literal["preparing", "ready", "executing", "completed", "partial", "unknown"]
    items: list[HostExecutionItem]
    excluded: list[HostExcluded]


class HostExecutionSelection(HostModel):
    item_id: NonEmptyString
    material_revision: NonEmptyString
    body: str
    attachment_digests: list[str]


class HostExecutionRequest(HostModel):
    candidate_id: CandidateId
    operation_key: NonEmptyString
    batch_id: NonEmptyString
    selected: list[HostExecutionSelection] = Field(min_length=1)


class HostChannel(HostModel):
    channel: NonEmptyString
    label: NonEmptyString
    status: Literal["connected", "dropped", "unknown"]
    checked_at: AwareDatetime | None
    restore_requested_at: AwareDatetime | None


class HostSyncDifference(HostModel):
    job_id: NonEmptyString
    title: str
    detail: str


class HostSync(HostModel):
    status: Literal["unavailable", "current", "stale", "mismatch", "unknown", "failed"]
    message: str
    checked_at: AwareDatetime | None
    differences: list[HostSyncDifference]


class HostState(HostModel):
    protocol_version: Literal["1.0"] = "1.0"
    candidate_id: CandidateId
    jobs: list[HostJob]
    todos: list[HostTodo]
    channels: list[HostChannel]
    batches: list[HostBatch]
    receipts: list[HostReceipt]
    sync: HostSync
