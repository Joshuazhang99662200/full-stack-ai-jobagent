from datetime import UTC, datetime

import pytest

from jobagent.errors import (
    ContractValidationError,
    InvalidProviderOutputError,
    UserInterventionRequiredError,
)
from jobagent.outreach.preference_memory import PreferenceLearner, memory_digest
from jobagent.schemas.preference_memory import PreferenceMemory
from jobagent.schemas.sourcing_feedback import SourcingFeedback

NOW = datetime(2026, 10, 26, tzinfo=UTC)


def signal(action="revise", note=""):
    return SourcingFeedback(
        event_id="EVENT_ONE", idempotency_key="EVENT_ONE", candidate_id="CAND_TEST",
        job_id="JOB_ONE", source="manual", query_strategy_version="V1", action=action,
        reason_category="other", free_text=note, content_digest="sha256:test",
        actor_id="OWNER", occurred_at=NOW, original_text="Original synthetic greeting",
        revised_text="Lead with model evaluation" if action == "revise" else None,
        jd_text="Build model evaluation products.", job_title="Evaluation PM", company="Synthetic",
    )


class Provider:
    def __init__(self, *, foreign=False, globalize=False, error=False):
        self.calls = []
        self.foreign, self.globalize, self.error = foreign, globalize, error

    def generate(self, *, prompt_id, context, output_type):
        self.calls.append((prompt_id, context))
        if self.error:
            raise UserInterventionRequiredError("timeout")
        if "summarize" in prompt_id:
            return output_type.model_validate({
                "input_digest": context["input_digest"],
                "rules": [{
                    "rule_id": "RULE_ONE", "category": "greetings",
                    "scope": "general" if self.globalize else "job",
                    "condition": "Model evaluation role", "job_id": None if self.globalize
                    else "JOB_ONE", "text": "Lead with evaluation work.",
                    "source_event_ids": ["EVENT_FOREIGN" if self.foreign else "EVENT_ONE"],
                    "updated_at": NOW.isoformat(),
                }],
            })
        return output_type.model_validate({
            "input_digest": context["input_digest"], "selected_rule_ids": ["RULE_ONE"],
            "search_queries": [],
        })


def empty():
    return PreferenceMemory(candidate_id="CAND_TEST", updated_at=NOW)


def test_summarizes_once_and_binds_consumed_events():
    provider = Provider()
    learner = PreferenceLearner(provider)
    updated = learner.update(empty(), [signal()], now=NOW)
    assert updated.consumed_event_ids == ["EVENT_ONE"]
    assert updated.rules[0].source_event_ids == ["EVENT_ONE"]
    assert learner.update(updated, [signal()], now=NOW) == updated
    assert len(provider.calls) == 1
    assert updated.version != empty().version


def test_foreign_sources_and_unjustified_globalization_are_rejected():
    with pytest.raises(InvalidProviderOutputError):
        PreferenceLearner(Provider(foreign=True)).update(empty(), [signal()], now=NOW)
    with pytest.raises(InvalidProviderOutputError):
        PreferenceLearner(Provider(globalize=True)).update(empty(), [signal()], now=NOW)


def test_failed_summary_does_not_consume_events():
    memory = empty()
    with pytest.raises(UserInterventionRequiredError):
        PreferenceLearner(Provider(error=True)).update(memory, [signal()], now=NOW)
    assert memory.consumed_event_ids == [] and memory.rules == []


def test_search_and_other_jd_do_not_receive_local_copy_rule():
    learner = PreferenceLearner(Provider())
    memory = learner.update(empty(), [signal()], now=NOW)
    assert learner.select(memory, task="search", job_id=None, context="Find jobs").rules == []
    assert learner.select(memory, task="greeting", job_id="JOB_OTHER",
                          context="Build sales tools").rules == []
    selected = learner.select(memory, task="greeting", job_id="JOB_ONE",
                              context="Build evaluation products")
    assert selected.rules[0].rule_id == "RULE_ONE"
    assert selected.memory_digest == memory_digest(memory)


def test_default_greeting_cannot_take_single_job_rules():
    learner = PreferenceLearner(Provider())
    memory = learner.update(empty(), [signal()], now=NOW)
    assert learner.select(memory, task="greeting", job_id=None,
                          context="Generic default greeting").rules == []


def test_foreign_candidate_is_rejected_before_any_model_call():
    provider = Provider()
    event = signal().model_copy(update={"candidate_id": "CAND_OTHER"})
    with pytest.raises(ContractValidationError, match="another candidate"):
        PreferenceLearner(provider).update(empty(), [event], now=NOW)
    assert not provider.calls


def test_jd_decline_cannot_become_a_copy_preference():
    with pytest.raises(InvalidProviderOutputError, match="does not judge"):
        PreferenceLearner(Provider()).update(empty(), [signal(action="decline")], now=NOW)


def test_unexplained_rejection_cannot_become_role_wide_preference():
    class Overgeneralizing(Provider):
        def generate(self, **kwargs):
            result = super().generate(**kwargs)
            if hasattr(result, "rules"):
                result.rules[0] = result.rules[0].model_copy(update={
                    "category": "jobs", "scope": "role", "job_id": None,
                })
            return result
    with pytest.raises(InvalidProviderOutputError):
        PreferenceLearner(Overgeneralizing()).update(empty(), [signal(action="decline")], now=NOW)
