from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

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


@pytest.mark.parametrize("changed", [
    {"free_text": "Different owner feedback under the same ID."},
    {"revised_text": "A different revised greeting."},
    {"actor_id": "ANOTHER_ACTOR"},
    {"jd_text": "A different job description."},
    {"content_digest": "sha256:replacement"},
    {"occurred_at": NOW + timedelta(seconds=1)},
])
def test_consumed_event_replay_rejects_changed_content_before_model_call(changed):
    provider = Provider()
    learner = PreferenceLearner(provider)
    event = signal()
    memory = learner.update(empty(), [event], now=NOW)
    saved = memory.model_dump(mode="json")
    with pytest.raises(ContractValidationError, match="different content"):
        learner.update(memory, [event.model_copy(update=changed)], now=NOW)
    assert len(provider.calls) == 1
    assert memory.model_dump(mode="json") == saved


def test_consumed_event_with_equivalent_timezone_is_an_exact_replay():
    provider = Provider()
    learner = PreferenceLearner(provider)
    event = signal()
    memory = learner.update(empty(), [event], now=NOW)
    equivalent = event.model_copy(update={
        "occurred_at": NOW.astimezone(timezone(timedelta(hours=8))),
    })
    assert learner.update(memory, [equivalent], now=NOW) == memory
    assert len(provider.calls) == 1


def test_legacy_consumed_event_without_digest_cannot_be_certified_by_replay():
    provider = Provider()
    legacy = PreferenceMemory(
        candidate_id="CAND_TEST", version="PMEM_LEGACY",
        consumed_event_ids=["EVENT_ONE"], updated_at=NOW,
    )
    with pytest.raises(ContractValidationError, match="no saved digest"):
        PreferenceLearner(provider).update(legacy, [signal()], now=NOW)
    assert not provider.calls
    assert legacy.version == "PMEM_LEGACY"


def test_fresh_feedback_records_digest_without_backfilling_legacy_sources():
    legacy = PreferenceMemory(
        candidate_id="CAND_TEST", version="PMEM_LEGACY",
        consumed_event_ids=["EVENT_LEGACY"], updated_at=NOW,
    )
    memory = PreferenceLearner(Provider()).update(legacy, [signal()], now=NOW)
    assert set(memory.consumed_event_digests) == {"EVENT_ONE"}
    assert memory.consumed_event_digests["EVENT_ONE"].startswith("sha256:")
    assert len(memory.consumed_event_digests["EVENT_ONE"]) == 71
    assert memory.consumed_event_ids == ["EVENT_LEGACY", "EVENT_ONE"]
    assert legacy.consumed_event_digests == {}


@pytest.mark.parametrize("digests", [
    {"EVENT_FOREIGN": "sha256:" + "a" * 64},
    {"EVENT_ONE": "sha256:invalid"},
])
def test_consumed_event_digests_require_real_hashes_and_known_ids(digests):
    with pytest.raises(ValidationError):
        PreferenceMemory(
            candidate_id="CAND_TEST", consumed_event_ids=["EVENT_ONE"],
            consumed_event_digests=digests, updated_at=NOW,
        )


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


@pytest.mark.parametrize("change", [
    {"text": "Use a different style without new supporting feedback."},
    {"rule_id": "RULE_RELABELED"},
    {"scope": "general", "job_id": None},
])
def test_replayed_old_source_cannot_support_new_or_changed_rules(change):
    old_event = signal(note="Keep the greeting short for this job.")
    memory = PreferenceLearner(Provider()).update(empty(), [old_event], now=NOW)
    fresh = signal(note="Research greetings should begin with the question.").model_copy(update={
        "event_id": "EVENT_TWO", "idempotency_key": "EVENT_TWO", "job_id": "JOB_TWO",
    })

    class Rewriter:
        def generate(self, *, prompt_id, context, output_type):
            assert [e["event_id"] for e in context["events"]] == ["EVENT_TWO"]
            return output_type(
                input_digest=context["input_digest"],
                rules=[memory.rules[0].model_copy(update=change)],
            )

    saved = memory.model_dump(mode="json")
    with pytest.raises(InvalidProviderOutputError, match="fresh owner source"):
        PreferenceLearner(Rewriter()).update(memory, [old_event, fresh], now=NOW)
    assert memory.model_dump(mode="json") == saved


def test_replayed_history_does_not_prevent_unchanged_rules_and_supported_new_rules():
    old_event = signal(note="Keep the greeting short for this job.")
    memory = PreferenceLearner(Provider()).update(empty(), [old_event], now=NOW)
    fresh = signal(note="Research greetings should begin with the question.").model_copy(update={
        "event_id": "EVENT_TWO", "idempotency_key": "EVENT_TWO", "job_id": "JOB_TWO",
    })
    new_rule = memory.rules[0].model_copy(update={
        "rule_id": "RULE_TWO", "job_id": "JOB_TWO", "source_event_ids": ["EVENT_TWO"],
        "text": "Lead with the research question.",
    })

    class Preserver:
        def generate(self, *, prompt_id, context, output_type):
            return output_type(input_digest=context["input_digest"],
                               rules=[memory.rules[0], new_rule])

    updated = PreferenceLearner(Preserver()).update(memory, [old_event, fresh], now=NOW)
    assert updated.rules == [memory.rules[0], new_rule]
    assert updated.consumed_event_ids == ["EVENT_ONE", "EVENT_TWO"]
    assert memory.consumed_event_ids == ["EVENT_ONE"]


def test_new_feedback_can_support_a_real_change_to_an_existing_rule():
    old_event = signal(note="Keep the greeting short for this job.")
    memory = PreferenceLearner(Provider()).update(empty(), [old_event], now=NOW)
    fresh = signal(note="For this job, lead with the evaluation result.").model_copy(update={
        "event_id": "EVENT_TWO", "idempotency_key": "EVENT_TWO",
    })
    changed = memory.rules[0].model_copy(update={
        "text": "Lead with the evaluation result.",
        "source_event_ids": ["EVENT_ONE", "EVENT_TWO"],
    })

    class SupportedRewriter:
        def generate(self, *, prompt_id, context, output_type):
            return output_type(input_digest=context["input_digest"], rules=[changed])

    updated = PreferenceLearner(SupportedRewriter()).update(memory, [old_event, fresh], now=NOW)
    assert updated.rules == [changed]
    assert updated.previous_version == memory.version
