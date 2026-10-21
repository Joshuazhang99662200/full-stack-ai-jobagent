"""The person's online profile on each board, as the boards showed it.

The profile is one shared background description kept on every board. Each read
is kept whole as a snapshot; a new version opens only when its digest changes, so
outcomes can be compared across the profile versions recruiters actually saw.
Profile text stays in the local database and is never echoed in reports.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, model_validator

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
