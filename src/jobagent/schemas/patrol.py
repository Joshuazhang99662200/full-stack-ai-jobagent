"""When the host patrols the boards, and how often.

A patrol fetches new postings, then reads messages. The person sets the weekly
windows and the rhythm; the repository answers "is a check due now" from the
recorded checks and the latest recruiter message, so a scheduler that wakes
often can still patrol at exactly the agreed pace. A patrol never sends on its
own: greetings and replies still go through their approvals.
"""

from datetime import datetime, time
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from jobagent.schemas.common import ContractModel, NonEmptyString

PatrolCheckId = Annotated[str, Field(pattern=r"^PCHECK_[A-Z0-9_]+$")]
PatrolSnapshotId = Annotated[str, Field(pattern=r"^PSNAP_[A-Z0-9_]+$")]


class PatrolWindow(ContractModel):
    """One weekly window in Shanghai time. Weekday 0 is Monday; `end` is exclusive."""

    weekday: Annotated[int, Field(ge=0, le=6)]
    start: time
    end: time | None = None  # None means midnight at the end of the day.

    @model_validator(mode="after")
    def require_order(self) -> "PatrolWindow":
        if self.end is not None and self.end <= self.start:
            raise ValueError("a window must end after it starts")
        return self


def _default_windows() -> list[PatrolWindow]:
    windows = [PatrolWindow(weekday=6, start=time(20, 0))]
    windows += [PatrolWindow(weekday=day, start=time(0, 0)) for day in range(4)]
    windows.append(PatrolWindow(weekday=4, start=time(0, 0), end=time(20, 0)))
    return windows


class PatrolSchedule(ContractModel):
    """Sunday 20:00-24:00, Monday to Thursday all day, Friday 00:00-20:00.

    One check an hour; within an hour of a recruiter's message, one every 15
    minutes. `slack_minutes` absorbs a scheduler that wakes a few minutes late.
    """

    windows: list[PatrolWindow] = Field(default_factory=_default_windows, min_length=1)
    base_interval_minutes: Annotated[int, Field(ge=15)] = 60
    escalated_interval_minutes: Annotated[int, Field(ge=15)] = 15
    escalation_minutes: Annotated[int, Field(ge=1)] = 60
    slack_minutes: Annotated[int, Field(ge=0, le=5)] = 3
    # A check started this long ago without finishing was cut off (for example the
    # session ran out of usage); the next wake resumes instead of waiting an hour.
    stale_minutes: Annotated[int, Field(ge=15)] = 45


class PatrolMode(StrEnum):
    OFF = "off"
    BASE = "base"
    ESCALATED = "escalated"


PATROL_STEPS = (
    "fetch_new_postings",
    "queue_greetings",
    "send_approved",
    "read_messages",
    "draft_replies",
)


class PatrolDecision(ContractModel):
    active: bool
    mode: PatrolMode
    due: bool
    interval_minutes: int | None = None
    last_check_at: datetime | None = None
    last_inbound_at: datetime | None = None
    next_check_at: datetime
    in_progress_check_id: str | None = None
    abandoned_check_id: str | None = None
    steps: list[str] = Field(default_factory=lambda: list(PATROL_STEPS))


class PatrolCheck(ContractModel):
    check_id: PatrolCheckId
    checked_at: datetime
    mode: PatrolMode
    finished_at: datetime | None = None


class SnapshotItem(ContractModel):
    """One conversation as the board's message list showed it. Recruiter text is data."""

    key: NonEmptyString  # stable per conversation, e.g. "赵先生|腾讯"
    recruiter: str = ""
    company: str = ""
    title: str | None = None
    salary: str | None = None
    preview: str = ""
    time_label: str = ""
    unread: Annotated[int, Field(ge=0)] = 0
    # Who sent the last message: the recruiter, us, a platform notice, or unknown.
    last_from: Literal["them", "us", "system", "unknown"] = "unknown"
    # What the board showed about our last message, when the host read it off the
    # page. Left unknown, it is read from the preview's status word instead.
    our_status: Literal["delivered", "read", "unknown"] = "unknown"


class PatrolSnapshot(ContractModel):
    """A board's whole message list at one moment, kept so the next check can diff it."""

    snapshot_id: PatrolSnapshotId
    platform: NonEmptyString
    captured_at: datetime
    check_id: PatrolCheckId | None = None
    items: list[SnapshotItem] = Field(default_factory=list)
    # Absent historical declarations stay labeled; they are not upgraded to a
    # verified login, full coverage or a confirmed empty message list.
    access_state: Literal[
        "authenticated", "public", "login_required", "loading", "verification",
        "risk_control", "unknown", "legacy_declared",
    ] = "legacy_declared"
    coverage: Literal["full", "partial", "unknown", "legacy_declared"] = "legacy_declared"
    load_state: Literal["loaded", "loading", "unknown", "legacy_declared"] = "legacy_declared"

    @model_validator(mode="after")
    def unique_conversation_keys(self) -> "PatrolSnapshot":
        keys = [item.key for item in self.items]
        if not self.legacy_declared and len(keys) != len(set(keys)):
            raise ValueError("Snapshot conversation keys must be unique.")
        return self

    @property
    def legacy_declared(self) -> bool:
        return (self.access_state, self.coverage, self.load_state) == (
            "legacy_declared", "legacy_declared", "legacy_declared",
        )

    @property
    def rows_observable(self) -> bool:
        keys = [item.key for item in self.items]
        return len(keys) == len(set(keys)) and (
            (self.legacy_declared and bool(self.items)) or (
                self.access_state in {"authenticated", "public"} and self.load_state == "loaded"
            )
        )

    @property
    def full_coverage_confirmed(self) -> bool:
        return self.rows_observable and self.coverage == "full"

    @property
    def baseline_eligible(self) -> bool:
        return self.rows_observable and (self.coverage == "full" or self.legacy_declared)


class SnapshotChange(ContractModel):
    before: SnapshotItem
    after: SnapshotItem


class SnapshotDiff(ContractModel):
    platform: NonEmptyString
    snapshot_id: PatrolSnapshotId
    previous_snapshot_id: PatrolSnapshotId | None = None
    new: list[SnapshotItem] = Field(default_factory=list)
    changed: list[SnapshotChange] = Field(default_factory=list)
    gone: list[str] = Field(default_factory=list)
    # New or changed conversations whose latest message is from the recruiter.
    their_new_messages: list[SnapshotItem] = Field(default_factory=list)
    comparison_status: Literal["compared", "initialized", "partial", "unavailable"] = "compared"


ReceiptStatus = Literal["delivered", "read"]


class ConversationReceipt(ContractModel):
    """A board showed our latest message in a conversation as delivered or read."""

    conversation_id: NonEmptyString
    status: ReceiptStatus
    observed_at: datetime
    snapshot_id: PatrolSnapshotId


class UnmatchedReceipt(ContractModel):
    """A status seen on a row no conversation could be matched to with certainty."""

    key: NonEmptyString
    status: ReceiptStatus
    reason: Literal["no_match", "ambiguous"]


class ReceiptReport(ContractModel):
    receipts: list[ConversationReceipt] = Field(default_factory=list)
    unmatched: list[UnmatchedReceipt] = Field(default_factory=list)
