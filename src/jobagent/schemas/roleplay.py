"""Local Gemini CLI configuration and the synthetic role-play memory evaluation contracts.

Everything here is for synthetic verification only: a role-play workspace holds a
synthetic candidate, synthetic postings and simulated owner decisions, and nothing
in it may be used for real outreach.
"""

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from jobagent.schemas.common import ContractModel, NonEmptyString

AUTO_APPROVE_FLAGS = frozenset({"--dangerously-skip-permissions", "--yolo", "-y"})


class GeminiCliConfig(ContractModel):
    """How this machine invokes a Gemini CLI.

    `gemini_json`: the Gemini CLI with `--output-format json`, which prints one envelope
    with `response` and `stats.tools.totalCalls`.
    `agy_stream_json`: the Antigravity CLI (`agy`) with `-p= --input-format stream-json
    --output-format stream-json`; the task goes in as one stream message and tool use is
    read from its step events, because its final result does not report tool calls.
    """

    argv: list[NonEmptyString] = Field(min_length=1, max_length=20)
    timeout_seconds: Annotated[float, Field(gt=0, le=600)]
    protocol: Literal["gemini_json", "agy_stream_json"] = "gemini_json"

    @model_validator(mode="after")
    def no_auto_approval(self) -> "GeminiCliConfig":
        if AUTO_APPROVE_FLAGS.intersection(self.argv):
            raise ValueError("The argv must not auto-approve tool use.")
        return self


class RoleplayEvidence(ContractModel):
    evidence_id: Annotated[str, Field(pattern=r"^EVID_[A-Z0-9_]+$")]
    statement: NonEmptyString
    skills: list[NonEmptyString] = Field(default_factory=list)


class RoleplayJob(ContractModel):
    source_job_id: NonEmptyString
    company: NonEmptyString
    title: NonEmptyString
    location: NonEmptyString
    url: NonEmptyString
    jd_raw: Annotated[str, Field(min_length=30)]


class HiddenPreference(ContractModel):
    """Known to the simulated owner only. Keywords let the harness check, without a
    judge model, whether memory rules came to express the preference."""

    preference_id: NonEmptyString
    description: NonEmptyString
    category: Literal["greetings", "jobs"]
    rule_keywords: list[NonEmptyString] = Field(min_length=1)


class RoleplayScenario(ContractModel):
    scenario_id: NonEmptyString
    candidate_id: Annotated[str, Field(pattern=r"^CAND_[A-Z0-9_]+$")]
    display_name: NonEmptyString
    persona: NonEmptyString
    evidence: list[RoleplayEvidence] = Field(min_length=1)
    hidden_preferences: list[HiddenPreference] = Field(min_length=1)
    jobs: list[RoleplayJob] = Field(min_length=2)

    @model_validator(mode="after")
    def unique_ids(self) -> "RoleplayScenario":
        for values in (
            [e.evidence_id for e in self.evidence],
            [p.preference_id for p in self.hidden_preferences],
            [j.source_job_id for j in self.jobs],
        ):
            if len(values) != len(set(values)):
                raise ValueError("Scenario identifiers must be unique.")
        return self


class RoleplayRound(ContractModel):
    round_number: int = Field(ge=1)
    job_id: NonEmptyString
    title: NonEmptyString
    company: NonEmptyString
    jd_raw: NonEmptyString
    generation_status: Literal["passed", "rejected"]
    greeting: str | None = None
    batch_id: str | None = None
    ask_id: str | None = None
    memory_version: NonEmptyString
    memory_rule_count: int = Field(ge=0)
    selected_rules: list[str] = Field(default_factory=list)
    selected_rule_texts: list[str] = Field(default_factory=list)
    unconsumed_events_before_generation: int = Field(ge=0)
    started_at: AwareDatetime


class RoleplayDecision(ContractModel):
    """The simulated owner's answer, in their own (synthetic) words."""

    action: Literal["approve", "revise", "decline"]
    words: NonEmptyString
    reason_category: Literal[
        "job_dislike", "salary", "location", "direction", "level", "copy", "facts", "later",
        "other",
    ] = "other"
    note: Annotated[str, Field(max_length=1000)] = ""
    revised_text: Annotated[str, Field(min_length=1, max_length=1000)] | None = None
    triggered_preferences: list[NonEmptyString] = Field(default_factory=list)

    @model_validator(mode="after")
    def revision_carries_words(self) -> "RoleplayDecision":
        if (self.action == "revise") != (self.revised_text is not None):
            raise ValueError("Only a revision carries revised words, and it must carry them.")
        return self


class RoleplayCheck(ContractModel):
    check_id: NonEmptyString
    passed: bool
    detail: str


class PreferenceCapture(ContractModel):
    preference_id: NonEmptyString
    triggered_rounds: list[int]
    captured: bool
    matching_rules: list[str]


class RoleplayReport(ContractModel):
    scenario_id: NonEmptyString
    rounds: int = Field(ge=0)
    decided: int = Field(ge=0)
    actions: dict[str, int]
    first_half_acceptance: float | None
    second_half_acceptance: float | None
    checks: list[RoleplayCheck]
    preferences: list[PreferenceCapture]
    memory_version: NonEmptyString
    memory_rules: list[str]
    synthetic_only: Literal[True] = True
