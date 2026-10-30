"""Portable owner signals and derived search priorities; never permissions."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from jobagent.schemas.candidate import CandidateId
from jobagent.schemas.common import ContractModel, Digest, NonEmptyString
from jobagent.schemas.job_intelligence import SourceJobRecord

SearchFeature = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=60),
]
OWNER_CHOICES = frozenset({"user_added", "like", "dislike"})


class SearchSignal(ContractModel):
    event_id: NonEmptyString
    candidate_id: CandidateId
    kind: Literal[
        "user_added",
        "like",
        "dislike",
        "greeting_edit",
        "recruiter_reply",
        "no_reply",
        "feedback",
    ]
    occurred_at: AwareDatetime
    job_preference: Literal["like", "dislike", "neutral"] | None = None
    message_feedback: Literal["accept", "revise", "reject"] | None = None
    query_term: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
        | None
    ) = None
    rejection_reason: (
        Literal[
            "direction",
            "salary",
            "location",
            "responsibilities",
            "level",
            "wording",
            "facts",
            "defer",
            "other",
        ]
        | None
    ) = None
    owner_text: str = ""
    job: SourceJobRecord
    features: dict[SearchFeature, NonEmptyString] = Field(default_factory=dict, max_length=12)
    rejected_features: list[SearchFeature] = Field(default_factory=list, max_length=12)

    @property
    def owner_preference(self) -> Literal["like", "dislike", "neutral"] | None:
        if self.kind in {"user_added", "like"}:
            return "like"
        if self.kind == "dislike":
            return "dislike"
        return self.job_preference if self.kind == "feedback" else None

    @model_validator(mode="after")
    def check_sources(self) -> "SearchSignal":
        if self.kind == "feedback":
            if self.job_preference is None and self.message_feedback is None:
                raise ValueError("Feedback must name a job preference or message decision.")
        elif self.job_preference is not None or self.message_feedback is not None:
            raise ValueError("Split decisions require kind=feedback.")
        if (self.owner_preference is not None or self.kind == "feedback") and (
            not self.owner_text.strip()
        ):
            raise ValueError("Owner choices require the actual owner's words.")
        if self.query_term is not None and self.query_term != self.job.search_term:
            raise ValueError("Query attribution must match the actual search discovery.")
        if self.rejection_reason == "direction" and self.owner_preference != "dislike":
            raise ValueError("Direction rejection requires an explicit job dislike.")
        if any(
            term not in quote or quote not in self.job.jd_raw
            for term, quote in self.features.items()
        ):
            raise ValueError("Features must be grounded in exact JD quotes.")
        if self.rejected_features and (
            self.owner_preference != "dislike"
            or any(
                term not in self.features or term not in self.owner_text
                for term in self.rejected_features
            )
        ):
            raise ValueError("Counterexamples require an explicitly named feature.")
        return self


class SearchLearningRequest(ContractModel):
    candidate_id: CandidateId
    baseline_queries: list[SearchFeature] = Field(min_length=1, max_length=10)
    signals: list[SearchSignal] = Field(default_factory=list, max_length=2000)

    @model_validator(mode="after")
    def check_isolation(self) -> "SearchLearningRequest":
        events: dict[str, SearchSignal] = {}
        choices: dict[tuple[str, str, AwareDatetime], SearchSignal] = {}
        for signal in self.signals:
            if signal.candidate_id != self.candidate_id:
                raise ValueError("Signals belong to another candidate.")
            if signal.event_id in events and signal != events[signal.event_id]:
                raise ValueError("The same event ID has different content.")
            events[signal.event_id] = signal
            key = (signal.job.source, signal.job.source_job_id, signal.occurred_at)
            if signal.owner_preference is not None:
                if key in choices and signal.model_dump(exclude={"event_id"}) != (
                    choices[key].model_dump(exclude={"event_id"})
                ):
                    raise ValueError("Owner choices at the same time are ambiguous.")
                choices[key] = signal
        return self


class SearchHypothesis(ContractModel):
    feature: SearchFeature
    status: Literal["proposed", "active", "contested"]
    support_event_ids: list[str]
    counter_event_ids: list[str]
    independent_companies: int = Field(ge=0)


class LearnedSearchPlan(ContractModel):
    candidate_id: CandidateId
    version: Digest
    ordered_queries: list[SearchFeature]
    hypotheses: list[SearchHypothesis]
    source_event_ids: list[str]
    changes_hard_constraints: Literal[False] = False
    grants_delivery_permission: Literal[False] = False
