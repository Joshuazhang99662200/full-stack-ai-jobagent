"""Signals the back-half evaluation needs: which rules were in force, and when.

A harness version names the files that steered drafting at one moment, by digest.
Outcomes are later compared across versions, so a change in a rate can be traced
to a change in the rules instead of being guessed at.
"""

from datetime import datetime
from typing import Annotated

from pydantic import Field

from jobagent.schemas.common import ContractModel, Digest, NonEmptyString

HarnessVersionId = Annotated[str, Field(pattern=r"^HVER_[A-Z0-9]+$")]


class HarnessFile(ContractModel):
    path: NonEmptyString
    digest: Digest


class HarnessVersion(ContractModel):
    """Content-addressed: the same files always give the same version."""

    version_id: HarnessVersionId
    digest: Digest
    files: list[HarnessFile] = Field(min_length=1)
    recorded_at: datetime
