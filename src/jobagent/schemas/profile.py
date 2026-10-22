"""The person's online profile on each board, as the boards showed it.

The profile is one shared background description kept on every board. Each read
is kept whole as a snapshot; a new version opens only when its digest changes, so
outcomes can be compared across the profile versions recruiters actually saw.
Profile text stays in the local database and is never echoed in reports.
"""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from jobagent.schemas.applications import ApprovalChannel
from jobagent.schemas.candidate import EvidenceId
from jobagent.schemas.common import ContractModel, Digest, NonEmptyString

ProfileSnapshotId = Annotated[str, Field(pattern=r"^PROFSNAP_[A-Z0-9_]+$")]
ProfileVersionId = Annotated[str, Field(pattern=r"^PROFVER_[A-Z0-9_]+$")]


class ProfileField(ContractModel):
    """One editable section of the profile, named the way the board's manifest names it."""

    name: NonEmptyString
    text: str = ""


class ProfileSnapshot(ContractModel):
    snapshot_id: ProfileSnapshotId
    platform: NonEmptyString
    captured_at: datetime
    fields: list[ProfileField] = Field(min_length=1)
    digest: Digest

    @model_validator(mode="after")
    def require_unique_field_names(self) -> "ProfileSnapshot":
        names = [field.name for field in self.fields]
        if len(names) != len(set(names)):
            raise ValueError("a profile names each field once")
        return self


class ProfileVersion(ContractModel):
    """A profile as it stood from `effective_at` until the next version.

    `baseline` is the first profile seen, `external` a change made outside this
    repository (by the person or the board). `agent` is reserved for changes the
    profile flywheel applies after the person approves them.
    """

    version_id: ProfileVersionId
    platform: NonEmptyString
    digest: Digest
    effective_at: datetime
    snapshot_id: ProfileSnapshotId
    origin: Literal["baseline", "external", "agent"]
    changed_fields: list[NonEmptyString] = Field(default_factory=list)
    previous_version_id: ProfileVersionId | None = None
    # For an `agent` version: the approval and proposal it put on the board.
    approval_id: str | None = None
    proposal_id: str | None = None


ProfileProposalId = Annotated[str, Field(pattern=r"^PROFPROP_[A-Z0-9_]+$")]
ProfileAskId = Annotated[str, Field(pattern=r"^PROFASK_[A-Z0-9_]+$")]
ProfileApprovalId = Annotated[str, Field(pattern=r"^PROFAPPR_[A-Z0-9_]+$")]
ProfileApplicationId = Annotated[str, Field(pattern=r"^PROFAPP_[A-Z0-9_]+$")]


class ProfileChange(ContractModel):
    """New words for one section the board already has."""

    name: NonEmptyString
    text: str


class ProfileTarget(ContractModel):
    platform: NonEmptyString
    # The version these changes were written against; a newer one makes them stale.
    base_version_id: ProfileVersionId
    changes: list[ProfileChange] = Field(min_length=1)


class ProfileProposalDraft(ContractModel):
    """What the agent wants each board's profile to say, and how it will be judged.

    The decision rule is written before anything goes live and is part of what the
    person approves, so the outcome cannot be judged by a rule picked afterwards.
    """

    targets: list[ProfileTarget] = Field(min_length=1)
    rationale: NonEmptyString
    evidence_ids: list[EvidenceId] = Field(min_length=1)
    decision_rule: NonEmptyString
    observation_workdays: Annotated[int, Field(ge=10)] = 10
    min_reads: Annotated[int, Field(ge=30)] = 30


class ProfileProposal(ProfileProposalDraft):
    proposal_id: ProfileProposalId
    # Per board: the digest the profile must have once the changes are in.
    expected_digests: dict[str, Digest]
    proposal_digest: Digest
    created_at: datetime


class ProfileAsk(ContractModel):
    """The changes put to a person, word for word. Asking approves nothing."""

    ask_id: ProfileAskId
    proposal_id: ProfileProposalId
    proposal_digest: Digest
    question: NonEmptyString
    asked_at: datetime


class ProfileApproval(ContractModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    approval_id: ProfileApprovalId
    proposal_id: ProfileProposalId
    proposal_digest: Digest
    ask_id: ProfileAskId
    approved_by: Literal["human"] = "human"
    channel: ApprovalChannel
    # The person's own words, verbatim.
    attestation: NonEmptyString
    approved_at: datetime


class ProfileApplyResult(StrEnum):
    APPLIED = "applied"
    # The board saved something other than what was approved.
    MISMATCH = "mismatch"
    FAILED = "failed"
    # Login, verification or risk control: a person must take over.
    INTERVENTION = "intervention"


class ProfileApplication(ContractModel):
    """One attempt to put an approved profile on one board. Never updated."""

    application_id: ProfileApplicationId
    proposal_id: ProfileProposalId
    approval_id: ProfileApprovalId
    platform: NonEmptyString
    result: ProfileApplyResult
    readback_snapshot_id: ProfileSnapshotId | None = None
    reason: str | None = None
    recorded_at: datetime


class ProfileGateDecision(ContractModel):
    allowed: bool
    reason: str | None = None
    platform: NonEmptyString
    # Only the sections to change, with the exact approved words.
    fields: list[ProfileField] = Field(default_factory=list)
    expected_digest: Digest | None = None
