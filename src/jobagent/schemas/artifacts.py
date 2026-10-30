"""Final employer-file identity; checks never grant delivery permission."""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator

from jobagent.schemas.common import ContractModel, NonEmptyString

ArtifactDigest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
ArtifactMediaType = Literal[
    "application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
]


class EmployerArtifact(ContractModel):
    path: NonEmptyString
    digest: ArtifactDigest
    media_type: ArtifactMediaType
    header_lines: list[NonEmptyString] = Field(default_factory=list)

    @field_validator("path")
    @classmethod
    def require_absolute_path(cls, value: str) -> str:
        if not Path(value).is_absolute():
            raise ValueError("Employer artifact path must be absolute.")
        return value


class ArtifactCheckReport(ContractModel):
    digest: ArtifactDigest
    media_type: ArtifactMediaType | None = None
    passed: bool
    issues: list[str] = Field(default_factory=list)
