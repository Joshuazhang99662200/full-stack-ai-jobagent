"""Summarize owner signals into small notes, then select notes for this task."""

from datetime import datetime
from typing import Any

from pydantic import ValidationError

from jobagent.capabilities import ReasoningOutputT, ReasoningProvider
from jobagent.errors import ContractValidationError, InvalidProviderOutputError
from jobagent.outreach.generation import content_digest
from jobagent.schemas.preference_memory import (
    PreferenceApplication,
    PreferenceMemory,
    PreferenceSelection,
    PreferenceUpdate,
)
from jobagent.schemas.sourcing_feedback import SourcingFeedback

SUMMARIZE_PROMPT = "preference.memory.summarize.v1"
SELECT_PROMPT = "preference.memory.select.v1"


def memory_digest(memory: PreferenceMemory) -> str:
    return content_digest(memory.model_dump(mode="json"))


class PreferenceLearner:
    def __init__(self, provider: ReasoningProvider) -> None:
        self.provider = provider

    def _generate(
        self, prompt: str, context: dict[str, Any], contract: type[ReasoningOutputT],
    ) -> ReasoningOutputT:
        try:
            raw = self.provider.generate(prompt_id=prompt, context=context, output_type=contract)
            return contract.model_validate(raw.model_dump())
        except (ValidationError, TypeError, AttributeError):
            raise InvalidProviderOutputError(
                "The preference proposal is not valid bounded data."
            ) from None

    def update(
        self, memory: PreferenceMemory, events: list[SourcingFeedback], *, now: datetime,
    ) -> PreferenceMemory:
        memory = PreferenceMemory.model_validate(memory.model_dump())
        unique: dict[str, SourcingFeedback] = {}
        for event in events:
            event = SourcingFeedback.model_validate(event.model_dump())
            if event.candidate_id != memory.candidate_id:
                raise ContractValidationError("Preference feedback belongs to another candidate.")
            if event.event_id in unique and unique[event.event_id] != event:
                raise ContractValidationError("The same preference event has different content.")
            unique[event.event_id] = event
        fresh = [event for event in unique.values()
                 if event.event_id not in memory.consumed_event_ids]
        if not fresh:
            return memory
        context = {"memory": memory.model_dump(mode="json"),
                   "events": [event.model_dump(mode="json") for event in fresh]}
        identity = content_digest(context)
        proposal = self._generate(
            SUMMARIZE_PROMPT, {**context, "input_digest": identity}, PreferenceUpdate,
        )
        if proposal.input_digest != identity:
            raise InvalidProviderOutputError("Preference summary has a stale input digest.")
        known = set(memory.consumed_event_ids) | set(unique)
        old_rules = {rule.rule_id: rule for rule in memory.rules}
        for rule in proposal.rules:
            if not set(rule.source_event_ids) <= known:
                raise InvalidProviderOutputError("Preference rule refers to an unknown source.")
            sources = [unique[eid] for eid in rule.source_event_ids if eid in unique]
            if not sources and old_rules.get(rule.rule_id) != rule:
                raise InvalidProviderOutputError("Changed preferences need a fresh owner source.")
            if rule.scope == "job" and sources and not any(
                event.job_id == rule.job_id for event in sources
            ):
                raise InvalidProviderOutputError("Job-specific memory refers to a different JD.")
            # Unexplained individual decisions cannot become general restrictions.
            if (rule.scope == "general" and len(set(rule.source_event_ids)) < 2
                    and sources and not any(event.free_text.strip() for event in sources)):
                raise InvalidProviderOutputError(
                    "An unexplained single decision cannot become a general preference."
                )
            if rule.category == "greetings" and sources and all(
                event.action == "decline" for event in sources
            ):
                raise InvalidProviderOutputError("A JD rejection does not judge the greeting.")
            if (rule.category == "jobs" and rule.scope != "job" and len(sources) == 1
                    and sources[0].action == "decline" and not sources[0].free_text.strip()):
                raise InvalidProviderOutputError(
                    "An unexplained JD rejection must stay specific to that JD."
                )
        consumed = list(dict.fromkeys([*memory.consumed_event_ids,
                                      *(event.event_id for event in fresh)]))
        try:
            result = PreferenceMemory(
                candidate_id=memory.candidate_id,
                version="PMEM_" + content_digest([memory.version, identity,
                                                   proposal.model_dump(mode="json")])[7:27].upper(),
                previous_version=memory.version, consumed_event_ids=consumed,
                rules=proposal.rules, updated_at=now,
            )
        except ValidationError:
            raise InvalidProviderOutputError(
                "Preference summary has inconsistent sources."
            ) from None
        return result

    def select(
        self, memory: PreferenceMemory, *, task: str, job_id: str | None, context: str,
    ) -> PreferenceSelection:
        memory = PreferenceMemory.model_validate(memory.model_dump())
        if task not in {"search", "greeting"}:
            raise ContractValidationError("Unknown preference-consumption task.")
        category = "jobs" if task == "search" else "greetings"
        eligible = [rule for rule in memory.rules if rule.category == category
                    and (rule.scope != "job" or rule.job_id == job_id)
                    and (job_id is not None or task == "search" or rule.scope == "general")]
        selection = PreferenceSelection(memory_version=memory.version,
                                        memory_digest=memory_digest(memory))
        if not eligible:
            return selection
        # The model may only choose IDs from host-filtered applicable categories.
        view = memory.model_copy(update={"rules": eligible}).model_dump(mode="json")
        payload = {"memory": view, "task": task, "job_id": job_id, "context": context}
        identity = content_digest(payload)
        applied = self._generate(SELECT_PROMPT, {**payload, "input_digest": identity},
                                 PreferenceApplication)
        by_id = {rule.rule_id: rule for rule in eligible}
        if (applied.input_digest != identity
                or not set(applied.selected_rule_ids) <= set(by_id)
                or len(set(applied.selected_rule_ids)) != len(applied.selected_rule_ids)
                or (task != "search" and applied.search_queries)):
            raise InvalidProviderOutputError("Preference selection is stale or outside its scope.")
        selection.rules = [by_id[key] for key in applied.selected_rule_ids]
        selection.search_queries = applied.search_queries
        return selection
