"""Domain-neutral, source-bound JD factors and editable lexicon policies."""

import re
from datetime import date
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from jobagent.schemas.candidate import CandidateId
from jobagent.schemas.common import ContractModel, Digest
from jobagent.schemas.job_intelligence import SearchRun
from jobagent.schemas.jobs import JobId
from jobagent.schemas.search_learning import SearchFeature, SearchLearningRequest
from jobagent.schemas.sourcing import BudgetProfile, QueryBudget

FeatureDimension = Literal["domain", "scenario", "tech", "role", "hard", "negative"]
TermText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100, pattern=r"^[^|\r\n]+$"),
]


class LexiconTerm(ContractModel):
    dimension: FeatureDimension
    term: TermText
    aliases: list[TermText] = Field(default_factory=list, max_length=20)
    count: int = Field(default=0, ge=0)
    last_seen: date | None = None
    source: Literal["JD快照", "人工反馈", "人工"] = "JD快照"
    note: str = ""
    weight: float = Field(default=1.0, ge=0, le=10)
    preference_weight: float = Field(default=0.0, ge=0, le=0.2)
    seed: bool = False
    author: TermText | None = None
    round_id: TermText | None = None
    source_refs: list[str] = Field(default_factory=list)
    independent_companies: int = Field(default=0, ge=0)
    maturity: Literal["observed_once", "repeated", "stable"] = "observed_once"

    @model_validator(mode="after")
    def check_manual_source(self) -> "LexiconTerm":
        if self.seed and self.source != "人工":
            raise ValueError("Only explicitly authored manual seeds bypass maturity.")
        if self.source == "人工" and (self.author is None or self.round_id is None):
            raise ValueError("Manual terms need author and round attribution.")
        if "|" in self.note or "\n" in self.note:
            raise ValueError("Notes cannot contain Markdown field delimiters.")
        return self


class Lexicon(ContractModel):
    lexicon_version: Annotated[str, Field(pattern=r"^v[1-9]\d*$")]
    domain: TermText
    updated_at: date
    based_on_snapshots: int = Field(ge=0)
    based_on_feedback_events: int = Field(ge=0)
    terms: list[LexiconTerm] = Field(default_factory=list, max_length=200)
    combinations: list[str] = Field(
        default_factory=lambda: [
            "{domain} {role}",
            "{domain} {scenario} {role}",
            "{scenario} {tech} {role}",
            "{domain} {tech} {role}",
        ],
        max_length=12,
    )
    derivation_digest: Digest | None = None
    parent_digest: Digest | None = None
    feedback_event_ids: list[str] = Field(default_factory=list)
    snapshot_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_terms(self) -> "Lexicon":
        keys = [(term.dimension, term.term.casefold()) for term in self.terms]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate canonical terms in one dimension.")
        allowed = {"domain", "scenario", "tech", "role"}
        for template in self.combinations:
            fields = re.findall(r"\{([a-z_]+)\}", template)
            remainder = re.sub(r"\{[a-z_]+\}", "", template).strip()
            if not 2 <= len(fields) <= 4 or len(set(fields)) != len(fields):
                raise ValueError("Templates need two to four distinct components.")
            if remainder or not set(fields) <= allowed:
                raise ValueError("Templates only accept positive facet placeholders.")
        order = {
            value: index
            for index, value in enumerate(
                ["domain", "scenario", "tech", "role", "hard", "negative"],
            )
        }
        object.__setattr__(
            self,
            "terms",
            sorted(
                self.terms,
                key=lambda term: (order[term.dimension], term.term.casefold()),
            ),
        )
        return self


class JDFeature(ContractModel):
    dimension: FeatureDimension
    term: TermText
    evidence: Annotated[str, Field(min_length=1)]
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    polarity: Literal["positive", "negated", "uncertain"] = "positive"
    requirement_level: Literal["required", "preferred", "unspecified"] = "unspecified"


class JDFeatureSet(ContractModel):
    snapshot_id: str
    job_id: JobId
    snapshot_version: int = Field(ge=1)
    jd_text_hash: Digest
    company: str | None = None
    fetched_at: AwareDatetime | None = None
    completeness: Literal["full", "listing", "partial"] = "full"
    features: list[JDFeature] = Field(default_factory=list, max_length=200)
    factor_summary: str = ""
    factorization_version: Literal["jd-features-v1"] = "jd-features-v1"
    factorization: Literal["deterministic", "model", "fallback"] = "deterministic"
    issues: list[str] = Field(default_factory=list)


class LexiconUpdateResult(ContractModel):
    lexicon: Lexicon
    version_digest: Digest
    changed: bool
    source_event_ids: list[str]
    ignored_event_ids: list[str]


class CombinationInput(QueryBudget):
    candidate_id: CandidateId
    source: TermText
    cooldown_hours: int = Field(default=24, ge=1, le=720)
    baseline_queries: list[SearchFeature] = Field(min_length=1, max_length=10)
    learning: SearchLearningRequest | None = None

    @model_validator(mode="after")
    def isolate_candidate(self) -> "CombinationInput":
        if self.learning is not None and self.learning.candidate_id != self.candidate_id:
            raise ValueError("Learning belongs to another candidate.")
        return self


class CombinationRequest(CombinationInput):
    now: AwareDatetime
    feature_sets: list[JDFeatureSet] = Field(default_factory=list, max_length=2000)
    history: list[SearchRun] = Field(default_factory=list, max_length=10000)


class CombinationQuery(ContractModel):
    query: Annotated[str, Field(min_length=1, max_length=200)]
    combination: dict[FeatureDimension, str]
    weight: float = Field(ge=0)
    reason: str
    source: str
    snapshot_ids: list[str] = Field(default_factory=list)
    feedback_event_ids: list[str] = Field(default_factory=list)
    demoted: bool = False


class CombinationPlan(ContractModel):
    budget_profile: BudgetProfile = "conservative"
    candidate_id: CandidateId
    source: str
    version: Digest
    lexicon_version: str
    status: Literal["ready", "needs_seed", "cooldown"]
    ordered_queries: list[CombinationQuery]
    deferred_queries: list[CombinationQuery]
    fallback_queries: list[str] = Field(default_factory=list)
    grants_delivery_permission: Literal[False] = False
