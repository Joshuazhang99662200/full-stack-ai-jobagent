"""Domain-neutral, source-bound JD factors and editable lexicon policies."""

from datetime import date
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from jobagent.schemas.common import ContractModel, Digest
from jobagent.schemas.jobs import JobId

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
    weight: float = Field(default=1, ge=0, le=10)
    preference_weight: float = Field(default=0, ge=0, le=0.2)
    seed: bool = False
    author: TermText | None = None
    round_id: TermText | None = None
    source_refs: list[str] = Field(default_factory=list)

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
        ],
        max_length=12,
    )
    derivation_digest: Digest | None = None
    parent_digest: Digest | None = None

    @model_validator(mode="after")
    def unique_terms(self) -> "Lexicon":
        keys = [(term.dimension, term.term.casefold()) for term in self.terms]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate canonical terms in one dimension.")
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
    features: list[JDFeature] = Field(default_factory=list, max_length=200)
    factor_summary: str = ""
    factorization_version: Literal["jd-features-v1"] = "jd-features-v1"
    factorization: Literal["deterministic", "model", "fallback"] = "deterministic"
    issues: list[str] = Field(default_factory=list)
