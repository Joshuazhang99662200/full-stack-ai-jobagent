"""Host observations are scoped to a board and page surface, never inferred replies."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from jobagent.schemas.candidate import CandidateId
from jobagent.schemas.common import ContractModel, NonEmptyString
from jobagent.schemas.sent_tracking import TrackingKey


class HostPageObservation(ContractModel):
    observation_id: TrackingKey
    candidate_id: CandidateId
    source: NonEmptyString
    surface: Literal["messages", "search"]
    state: Literal["logged_in", "login_redirect", "not_loaded"]
    observed_at: AwareDatetime
    evidence_reference: NonEmptyString
    reload_count: int = Field(default=0, ge=0, le=1)


class HostRoundInput(ContractModel):
    report_id: TrackingKey
    candidate_id: CandidateId
    domain: NonEmptyString
    run_ids: list[NonEmptyString] = Field(min_length=1, max_length=20)
    started_at: AwareDatetime
    completed_at: AwareDatetime
    search_observation_ids: list[str] = Field(default_factory=list, max_length=5000)
    manual_observation_ids: list[str] = Field(default_factory=list, max_length=5000)
    dedup_count: int | None = Field(default=None, ge=0)
    filter_reasons: dict[str, Annotated[int, Field(ge=0)]] | None = None
    metrics_evidence_reference: str | None = None
    unfinished: list[str] = Field(default_factory=list)
    evidence_mode: Literal["unverified", "synthetic", "host_observed"] = "unverified"
    host_evidence_reference: str | None = None

    @model_validator(mode="after")
    def original_observations(self) -> "HostRoundInput":
        if self.completed_at < self.started_at:
            raise ValueError("Round completion cannot precede its start.")
        if (
            self.dedup_count is not None or self.filter_reasons is not None
        ) and not self.metrics_evidence_reference:
            raise ValueError("Host counters require the original observation reference.")
        if self.evidence_mode == "host_observed" and not self.host_evidence_reference:
            raise ValueError("Host-observed reports need their private execution evidence.")
        if len(set(self.run_ids)) != len(self.run_ids):
            raise ValueError("A round cannot repeat the same run.")
        if len(set(self.search_observation_ids)) != len(self.search_observation_ids):
            raise ValueError("Search observations cannot be duplicated to inflate attribution.")
        if set(self.search_observation_ids) & set(self.manual_observation_ids):
            raise ValueError("A discovery cannot be both manual and search.")
        return self


class HostTwoRoundInput(ContractModel):
    candidate_id: CandidateId
    first_report_id: TrackingKey
    second_report_id: TrackingKey


class HostQueryExecution(ContractModel):
    attempt_id: str
    run_id: str
    candidate_id: CandidateId
    domain: str
    source: str
    query: str
    plan_id: str
    listing_count: int = Field(ge=0)
    new_count: int = Field(ge=0)
    completed_at: AwareDatetime
