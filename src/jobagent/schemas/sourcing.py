"""Host read reservations and explicit collection coverage; never send permissions."""

from typing import Literal

from pydantic import AwareDatetime, Field, HttpUrl, model_validator

from jobagent.schemas.common import ContractModel, Digest, NonEmptyString


class ReadReservation(ContractModel):
    attempt_id: NonEmptyString
    source: NonEmptyString
    target_url: HttpUrl
    profile: NonEmptyString
    expected_daily_cap: int = Field(ge=1, le=50)


class ReadOutcome(ContractModel):
    attempt_id: NonEmptyString
    status: Literal[
        "read", "failed", "login_required", "loading", "verification", "risk_control", "unknown",
    ]


class ReadReceipt(ContractModel):
    attempt_id: NonEmptyString
    source: NonEmptyString
    request_digest: Digest
    reserved_at: AwareDatetime
    daily_cap: int
    profile: NonEmptyString
    allowed: bool


class SourcingDisposition(ContractModel):
    item_id: NonEmptyString
    status: Literal[
        "draft_ready", "needs_jd", "rejected", "duplicate", "closed", "unsupported", "deferred",
    ]
    reason: NonEmptyString


class SourcingCompletion(ContractModel):
    input_ids: list[NonEmptyString]
    dispositions: list[SourcingDisposition]
    stop_reason: Literal["complete", "budget", "intervention", "interrupted"]
    last_cursor: str | None = None
    access_state: Literal[
        "public", "authenticated", "login_required", "loading", "verification",
        "risk_control", "unknown",
    ] = "unknown"
    loaded: bool = False

    @model_validator(mode="after")
    def account_for_every_input(self) -> "SourcingCompletion":
        output_ids = [row.item_id for row in self.dispositions]
        if (len(set(self.input_ids)) != len(self.input_ids)
                or len(set(output_ids)) != len(output_ids)
                or set(self.input_ids) != set(output_ids)):
            raise ValueError("Every input needs exactly one disposition.")
        if self.stop_reason != "complete" and not self.last_cursor:
            raise ValueError("Partial collection requires a recovery cursor.")
        if self.stop_reason == "complete" and (
            self.access_state not in {"public", "authenticated"} or not self.loaded
        ):
            raise ValueError("Complete collection requires an accessible loaded view.")
        return self
