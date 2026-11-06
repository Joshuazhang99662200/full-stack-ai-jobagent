"""P1 source inventory and deterministic context; no business authority or execution."""

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from jobagent.schemas.candidate import CandidateId
from jobagent.schemas.common import ContractModel, NonEmptyString
from jobagent.schemas.jobs import JobId


class MemorySource(ContractModel):
    source_id: NonEmptyString
    candidate_id: CandidateId
    kind: NonEmptyString
    path: NonEmptyString


class MemoryConfig(ContractModel):
    candidate_id: CandidateId
    private_root: NonEmptyString
    sources: list[MemorySource] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_sources(self) -> "MemoryConfig":
        ids = [source.source_id for source in self.sources]
        if len(set(ids)) != len(ids):
            raise ValueError("Memory source IDs must be unique.")
        return self


class MemorySourceRef(MemorySource):
    state: Literal["ready", "empty", "missing", "invalid", "unreadable", "not_integrated"]
    digest: str | None = None
    version: str | None = None
    evidence_level: Literal["validated_preference", "owner_confirmed", "host_reported", "unknown"]
    count: int | None = None
    diagnostics: list[str] = Field(default_factory=list)


class MemoryItem(ContractModel):
    source_id: str
    item_id: str
    candidate_id: CandidateId
    task: Literal["search", "greeting"]
    kind: Literal["soft_preference", "confirmed_rule"]
    text: str
    scope: Literal["general", "job", "role", "unsupported"]
    job_id: str | None = None
    condition: str | None = None


class MemoryRead(ContractModel):
    source: MemorySourceRef
    items: list[MemoryItem] = Field(default_factory=list)


class MemorySnapshot(ContractModel):
    snapshot_id: str
    candidate_id: CandidateId
    config_digest: str
    adapter_version: Literal["memory.p1.v1"] = "memory.p1.v1"
    compiled_at: datetime
    sources: list[MemorySourceRef]


class MemoryStatus(ContractModel):
    candidate_id: CandidateId
    sources: list[MemorySourceRef]
    snapshot_count: int
    usage_verified: Literal[False] = False
    learning_updated: Literal[False] = False


class MemoryContextBundle(ContractModel):
    candidate_id: CandidateId
    snapshot_id: str
    task: str
    job_id: JobId | None = None
    context_digest: str = ""
    status: Literal["ready", "blocked", "not_integrated"]
    usable: bool
    sources: list[MemorySourceRef] = Field(default_factory=list)
    items: list[MemoryItem] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)
    usage_verified: Literal[False] = False
    learning_updated: Literal[False] = False
    injection_evidence: Literal["not_recorded"] = "not_recorded"


class UsageCounts(ContractModel):
    drafted: int = Field(default=0, ge=0)
    approved: int = Field(default=0, ge=0)
    sent: int = Field(default=0, ge=0)


class MemoryVersionUsage(UsageCounts):
    memory_version: NonEmptyString | None
    dynamic_rules_version: NonEmptyString | None


class PreferenceRuleUsage(UsageCounts):
    rule_id: NonEmptyString
    memory_version: NonEmptyString


class MemoryUsageReport(ContractModel):
    """Ledger evidence of which memory and rules reached real outreach items.

    Counts only items whose source binding records the generation provenance;
    older or hand-written items are reported as unattributed, not guessed.
    """

    candidate_id: CandidateId
    memory_versions: list[MemoryVersionUsage] = Field(default_factory=list)
    rules: list[PreferenceRuleUsage] = Field(default_factory=list)
    unattributed: UsageCounts = Field(default_factory=UsageCounts)
    evidence: Literal["outreach_ledger"] = "outreach_ledger"
    grants_approval: Literal[False] = False


class SentOutreach(ContractModel):
    """One greeting with a positive send record, and the memory it was generated with."""

    batch_id: NonEmptyString
    number: int = Field(ge=1)
    job_id: JobId
    platform: NonEmptyString
    sent_at: datetime
    memory_version: NonEmptyString | None = None
    preference_rule_ids: list[NonEmptyString] = Field(default_factory=list)


class ReplyOutcome(SentOutreach):
    # pending: the observation window has not closed, so it is in no denominator.
    status: Literal["replied", "no_reply", "pending"]


class RateComparison(ContractModel):
    treated_replies: int = Field(ge=0)
    treated_sent: int = Field(ge=0)
    baseline_replies: int = Field(ge=0)
    baseline_sent: int = Field(ge=0)
    difference: float | None
    interval_low: float | None
    interval_high: float | None
    verdict: Literal["insufficient_sample", "higher", "lower", "no_clear_difference"]


class EffectGroup(ContractModel):
    label: NonEmptyString
    kind: Literal["memory_version", "rule"]
    comparison: RateComparison


class MemoryEffectReport(ContractModel):
    """Reply rates of memory-shaped greetings against greetings made without memory.

    Observational unless items carried a random assignment: a "higher" verdict is an
    association inside closed windows, not proof that the memory caused it.
    """

    candidate_id: CandidateId
    window_days: int = Field(ge=1)
    min_sample: int = Field(ge=1)
    observed_at: datetime
    pending: int = Field(ge=0)
    groups: list[EffectGroup] = Field(default_factory=list)
    assignment: Literal["observational"] = "observational"
    grants_approval: Literal[False] = False


class SimulationResult(ContractModel):
    """detection: correct-direction claims; false_claim: any claim when lift is 0;
    wrong_direction: claims opposite to a non-zero lift."""

    trials: int = Field(ge=1)
    sample_size: int = Field(ge=1)
    base_rate: float
    lift: float
    detection_rate: float
    false_claim_rate: float
    wrong_direction_rate: float
    insufficient_rate: float
