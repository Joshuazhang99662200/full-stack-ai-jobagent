"""Shared serialized contracts used across JobAgent domains."""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

NonEmptyString = Annotated[str, Field(min_length=1)]
Digest = Annotated[str, Field(pattern=r"^sha256:.+")]


class ContractModel(BaseModel):
    """Strict base for public, versioned JobAgent contracts."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    schema_version: Literal["1.0"] = "1.0"


class SourceType(StrEnum):
    RESUME = "resume"
    INTERVIEW = "interview"
    USER_EDIT = "user_edit"
    CONNECTOR = "connector"
    SYSTEM = "system"


class SourceReference(ContractModel):
    type: SourceType
    reference: NonEmptyString


class TimeRange(ContractModel):
    start: date | None = None
    end: date | None = None

    @model_validator(mode="after")
    def validate_chronology(self) -> "TimeRange":
        if self.start is not None and self.end is not None and self.end < self.start:
            raise ValueError("end must not be earlier than start")
        return self


class MoneyRange(ContractModel):
    currency: Annotated[str, Field(min_length=3, max_length=3)]
    minimum: Annotated[Decimal, Field(ge=0)] | None = None
    maximum: Annotated[Decimal, Field(ge=0)] | None = None
    period: NonEmptyString | None = None

    @model_validator(mode="after")
    def validate_bounds(self) -> "MoneyRange":
        if self.minimum is not None and self.maximum is not None and self.maximum < self.minimum:
            raise ValueError("maximum must not be less than minimum")
        return self


class ProvenanceRecord(ContractModel):
    source: NonEmptyString
    source_id: NonEmptyString
    url: HttpUrl | None = None
    collected_at: datetime
