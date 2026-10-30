import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from jobagent.cli.app import app

NOW = datetime(2026, 10, 27, tzinfo=UTC)


def signal(number=1, **changes):
    event = {
        "event_id": f"SIG_{number}", "candidate_id": "CAND_DEMO",
        "kind": "user_added", "occurred_at": NOW.isoformat(),
        "owner_text": "请把这个岗位作为我喜欢的方向样本。",
        "job": {
            "source": "boss", "source_job_id": str(number),
            "title": "产品经理", "company": f"合成公司{number}", "location": "上海",
            "jd_raw": "负责智能体产品设计与用户研究。", "url": f"https://example.com/job/{number}",
            "collected_at": NOW.isoformat(),
        },
        "features": {"智能体产品": "智能体产品设计"},
        "rejected_features": [],
    }
    event.update(changes)
    return event


def request(*signals):
    return {"candidate_id": "CAND_DEMO", "baseline_queries": ["产品经理"], "signals": signals}


def learn(payload):
    from jobagent.jobs.search_learning import learn_search
    from jobagent.schemas.search_learning import SearchLearningRequest

    return learn_search(SearchLearningRequest.model_validate(payload))


def test_cold_start_preserves_queries_without_claiming_permission():
    plan = learn(request())
    assert plan.ordered_queries == ["产品经理"]
    assert plan.hypotheses == []
    assert plan.changes_hard_constraints is False
    assert plan.grants_delivery_permission is False


def test_one_owner_added_job_is_only_a_proposal():
    plan = learn(request(signal()))
    assert plan.ordered_queries == ["产品经理"]
    assert plan.hypotheses[0].status == "proposed"
    assert plan.hypotheses[0].support_event_ids == ["SIG_1"]


def test_independent_owner_examples_add_a_bounded_query_and_keep_the_baseline():
    payload = request(signal(), signal(2, kind="like"))
    before = deepcopy(payload)
    plan = learn(payload)
    assert payload == before
    assert plan.ordered_queries == ["智能体产品", "产品经理"]
    assert plan.hypotheses[0].status == "active"
    assert plan.hypotheses[0].independent_companies == 2


def test_repeated_jobs_from_one_company_do_not_become_independent_support():
    second = signal(2)
    second["job"]["company"] = " 合成公司1 "
    assert learn(request(signal(), second)).hypotheses[0].status == "proposed"


def test_feature_specific_owner_counterexample_suspends_the_hypothesis():
    negative = signal(3, kind="dislike", owner_text="我不想做智能体产品。",
                      rejected_features=["智能体产品"])
    plan = learn(request(signal(), signal(2), negative))
    assert plan.hypotheses[0].status == "contested"
    assert plan.hypotheses[0].counter_event_ids == ["SIG_3"]
    assert plan.ordered_queries == ["产品经理"]


@pytest.mark.parametrize("kind", ["recruiter_reply", "no_reply", "greeting_edit", "dislike"])
def test_outcomes_and_unexplained_job_rejection_do_not_judge_features(kind):
    plan = learn(request(signal(), signal(2), signal(3, kind=kind)))
    assert plan.hypotheses[0].status == "active"
    assert plan.hypotheses[0].support_event_ids == ["SIG_1", "SIG_2"]
    assert plan.hypotheses[0].counter_event_ids == []


def test_latest_owner_decision_for_one_job_replaces_prior_support():
    later = signal(kind="dislike", event_id="SIG_RETRACT", owner_text="这个岗位不适合我。",
                   occurred_at=(NOW + timedelta(hours=1)).isoformat())
    plan = learn(request(signal(), signal(2), later))
    assert plan.hypotheses[0].status == "proposed"
    assert plan.hypotheses[0].support_event_ids == ["SIG_2"]
    assert set(plan.source_event_ids) == {"SIG_1", "SIG_2", "SIG_RETRACT"}


def test_observations_do_not_erase_an_earlier_owner_decision():
    later = signal(kind="no_reply", event_id="SIG_OBS",
                   occurred_at=(NOW + timedelta(hours=1)).isoformat())
    assert learn(request(signal(), signal(2), later)).hypotheses[0].status == "active"


def test_replay_and_input_order_are_idempotent():
    first, second = signal(), signal(2)
    plan = learn(request(first, second))
    assert learn(request(second, first, first)) == plan


@pytest.mark.parametrize("change", [
    {"candidate_id": "CAND_OTHER"},
    {"features": {"虚构": "JD没有这段话"}},
    {"features": {" ": "智能体产品设计"}},
    {"kind": "dislike", "rejected_features": ["智能体产品"], "owner_text": "薪资太低"},
    {"kind": "like", "rejected_features": ["智能体产品"]},
    {"occurred_at": "2026-10-27T00:00:00"},
    {"grants_delivery_permission": True},
])
def test_invalid_or_cross_candidate_signals_are_rejected(change):
    with pytest.raises(ValueError):
        learn(request(signal(**change)))


def test_same_event_id_with_changed_content_is_rejected():
    with pytest.raises(ValueError, match="event"):
        learn(request(signal(), signal(kind="like")))


def test_same_job_and_time_with_conflicting_owner_decisions_is_rejected():
    with pytest.raises(ValueError, match="ambiguous"):
        learn(request(signal(), signal(event_id="SIG_OTHER", kind="dislike")))


def test_at_most_two_new_queries_are_added():
    features = {"智能体": "智能体", "产品": "产品", "用户研究": "用户研究"}
    plan = learn(request(signal(features=features), signal(2, features=features)))
    assert len(plan.ordered_queries) == 3
    assert plan.ordered_queries[-1] == "产品经理"


def test_active_features_already_in_baseline_move_forward_without_duplication():
    payload = request(signal(), signal(2))
    payload["baseline_queries"] = ["产品经理", "智能体产品"]
    assert learn(payload).ordered_queries == ["智能体产品", "产品经理"]


def test_cli_computes_a_plan_without_creating_private_state(tmp_path: Path):
    payload = tmp_path / "signals.json"
    payload.write_text(json.dumps(request(signal(), signal(2))), encoding="utf-8")
    result = CliRunner().invoke(app, ["jobs", "learn-search", str(payload)])
    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["ordered_queries"] == ["智能体产品", "产品经理"]
    assert list(tmp_path.iterdir()) == [payload]


def test_cli_validation_error_does_not_echo_private_source_text(tmp_path: Path):
    payload = tmp_path / "signals.json"
    payload.write_text(json.dumps(request(signal(features={"invalid": "PRIVATE_SENTINEL"}))),
                       encoding="utf-8")
    result = CliRunner().invoke(app, ["jobs", "learn-search", str(payload)])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["code"] == "CONTRACT_VALIDATION_ERROR"
    assert "PRIVATE_SENTINEL" not in result.stdout


def test_explicit_job_like_and_message_revision_contribute_only_job_support():
    plan = learn(request(
        signal(kind="feedback", job_preference="like", message_feedback="revise"),
        signal(2, kind="feedback", job_preference="like", message_feedback="accept"),
    ))
    assert plan.hypotheses[0].status == "active"
    assert plan.grants_delivery_permission is False


@pytest.mark.parametrize("message", ["accept", "revise", "reject"])
def test_message_feedback_does_not_implicitly_like_or_dislike_a_job(message):
    plan = learn(request(signal(kind="feedback", message_feedback=message)))
    assert plan.hypotheses == []
    assert plan.ordered_queries == ["产品经理"]


def test_later_message_only_feedback_does_not_erase_explicit_job_like():
    later = signal(kind="feedback", message_feedback="revise", event_id="SIG_EDIT",
                   occurred_at=(NOW + timedelta(hours=1)).isoformat())
    plan = learn(request(signal(), signal(2), later))
    assert plan.hypotheses[0].status == "active"
    assert "SIG_EDIT" in plan.source_event_ids


def test_explicit_neutral_job_preference_retracts_earlier_support():
    later = signal(kind="feedback", job_preference="neutral", event_id="SIG_NEUTRAL",
                   occurred_at=(NOW + timedelta(hours=1)).isoformat())
    plan = learn(request(signal(), signal(2), later))
    assert plan.hypotheses[0].status == "proposed"
    assert plan.hypotheses[0].support_event_ids == ["SIG_2"]


def test_split_feedback_rejection_still_needs_explicit_feature_reason():
    negative = signal(3, kind="feedback", job_preference="dislike",
                      owner_text="我不想做智能体产品。", rejected_features=["智能体产品"])
    assert learn(request(signal(), signal(2), negative)).hypotheses[0].status == "contested"
    with pytest.raises(ValueError):
        learn(request(signal(3, kind="feedback", job_preference="dislike",
                             owner_text="薪资太低", rejected_features=["智能体产品"])))


@pytest.mark.parametrize("changes", [
    {"kind": "feedback"}, {"kind": "feedback", "message_feedback": "accept", "owner_text": ""},
    {"kind": "like", "message_feedback": "accept"},
])
def test_ambiguous_or_unattributed_split_feedback_is_rejected(changes):
    with pytest.raises(ValueError):
        learn(request(signal(**changes)))


def test_split_preference_participates_in_same_time_conflict_detection():
    with pytest.raises(ValueError, match="ambiguous"):
        learn(request(signal(), signal(event_id="SIG_OTHER", kind="feedback",
                                      job_preference="dislike")))


def test_message_only_event_at_same_time_can_coexist_with_a_job_preference():
    plan = learn(request(signal(), signal(2), signal(
        event_id="SIG_MSG", kind="feedback", message_feedback="revise",
    )))
    assert plan.hypotheses[0].status == "active"
