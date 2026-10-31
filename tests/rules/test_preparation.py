from datetime import UTC, datetime

from tests.rules.test_evaluation import profile

BASE_VALUES = {
    "QUERIES_PER_SITE_PER_ROUND": 2,
    "TOP_PER_QUERY": 7,
    "DETAIL_ATTEMPTS_PER_SITE_PER_ROUND": 19,
    "DETAIL_CAP_PER_DAY": 37,
}


def preparation(mode="ordinary_run", **changes):
    from jobagent.schemas.configuration import ConfigurationPreparationRequest

    return ConfigurationPreparationRequest(
        candidate_id="CAND_SYNTHETIC", task_id="TASK_SYNTHETIC", task_type="sourcing",
        mode=mode, **changes,
    )


def owner_request(**changes):
    from jobagent.schemas.dynamic_rules import OwnerChangeRequest

    data = dict(
        candidate_id="CAND_SYNTHETIC", names=["TOP_PER_QUERY"],
        owner_text="Change the per-query limit for my future tasks.",
        source_reference="synthetic owner message", actor_id="synthetic owner",
        requested_at=datetime(2026, 10, 2, tzinfo=UTC),
    )
    return OwnerChangeRequest.model_validate(data | changes)


def test_only_initial_setup_questions_for_missing_values():
    from jobagent.rules.preparation import prepare_configuration

    initial = prepare_configuration(preparation("initial_setup"), None, initialized=False)
    ordinary = prepare_configuration(preparation(), None, initialized=False)
    assert initial.ask_user and initial.status == "needs_user_decision"
    assert {field.name for field in initial.fields} == set(BASE_VALUES)
    assert len(initial.questions) == 4
    assert not ordinary.ask_user and ordinary.questions == [] and not ordinary.ready
    assert ordinary.status == "blocked_by_missing_configuration"


def test_completed_first_form_needs_only_machine_initialization():
    from jobagent.rules.preparation import prepare_configuration

    result = prepare_configuration(preparation("initial_setup"), profile(BASE_VALUES),
                                   initialized=False)
    assert result.status == "ready_to_initialize" and result.can_initialize
    assert not result.ask_user and not result.ready


def test_initialized_profile_reuses_values_across_task_types_and_setup_requests():
    from jobagent.rules.preparation import prepare_configuration

    snapshot = profile(BASE_VALUES)
    for kind in ["sourcing", "research", "recovery", "new-task-type"]:
        request = preparation("initial_setup").model_copy(update={"task_type": kind})
        result = prepare_configuration(request, snapshot, initialized=True)
        assert result.mode == "ordinary_run" and result.ready
        assert not result.ask_user and result.questions == []
        assert result.rules_version == snapshot.version
        assert {field.name: field.value for field in result.fields} == BASE_VALUES


def test_missing_or_conflicting_ordinary_config_never_reopens_questions():
    from jobagent.rules.preparation import prepare_configuration

    missing = prepare_configuration(preparation(), profile({"TOP_PER_QUERY": 7}),
                                    initialized=True)
    conflict = prepare_configuration(preparation(conflicts=["source_policy_conflict"]),
                                     profile(BASE_VALUES), initialized=True)
    unsupported = prepare_configuration(preparation(required_names=["FIRST_LAUNCH_MIN_JD"]),
                                        profile(BASE_VALUES | {"FIRST_LAUNCH_MIN_JD": 3}),
                                        initialized=True)
    for result in [missing, conflict, unsupported]:
        assert not result.ask_user and not result.ready and result.questions == []
    assert missing.status == "blocked_by_missing_configuration"
    assert conflict.status == "blocked_by_conflict"
    assert unsupported.status == "unsupported_consumer"


def test_explicit_owner_change_asks_only_named_fields():
    from jobagent.rules.preparation import prepare_configuration

    denied = prepare_configuration(preparation("owner_requested_change"),
                                   profile(BASE_VALUES), initialized=True)
    accepted = prepare_configuration(
        preparation("owner_requested_change", owner_request=owner_request()),
        profile(BASE_VALUES), initialized=True,
    )
    assert not denied.ask_user and denied.status == "blocked_by_conflict"
    assert accepted.ask_user and not accepted.ready
    assert len(accepted.questions) == 1 and "TOP_PER_QUERY" in accepted.questions[0]
    assert "DETAIL_ATTEMPTS_PER_SITE_PER_ROUND" not in accepted.questions[0]


def test_other_candidate_or_stale_version_cannot_become_ready():
    import pytest

    from jobagent.errors import ContractValidationError
    from jobagent.rules.preparation import prepare_configuration

    with pytest.raises(ContractValidationError, match="candidate"):
        prepare_configuration(preparation(), profile(BASE_VALUES, candidate_id="CAND_OTHER"),
                              initialized=True)
    result = prepare_configuration(preparation(expected_version="sha256:old"),
                                   profile(BASE_VALUES), initialized=True)
    assert not result.ask_user and result.status == "blocked_by_conflict"


def test_future_owner_request_cannot_open_configuration_questions():
    from jobagent.rules.preparation import prepare_configuration

    result = prepare_configuration(
        preparation("owner_requested_change", owner_request=owner_request()),
        profile(BASE_VALUES), initialized=True, now=datetime(2026, 10, 1, tzinfo=UTC),
    )
    assert not result.ask_user and result.questions == []
    assert result.status == "blocked_by_conflict"


def test_exact_change_question_displays_round_scope_without_changing_legacy_serialization():
    from jobagent.rules.service import make_proposal
    from tests.rules.test_dynamic_registry import request

    snapshot = profile(BASE_VALUES)
    change = request("TOP_PER_QUERY", 9)
    change.expected_version = snapshot.version
    change.provenance.decided_at = datetime(2026, 10, 2, tzinfo=UTC)
    change.owner_request = owner_request(scope="round", run_id="SYNTHETIC_ROUND")
    proposal = make_proposal(change, snapshot, now=change.provenance.decided_at)
    assert "round SYNTHETIC_ROUND only" in proposal.question
    assert "reusable settings unchanged" in proposal.question
    legacy = request()
    assert "owner_request" not in legacy.model_dump(mode="json")
    assert "Scope:" not in make_proposal(legacy, None, now=legacy.provenance.decided_at).question


def test_owner_request_older_than_current_field_decision_never_reopens_questions():
    from jobagent.rules.preparation import prepare_configuration
    from jobagent.rules.service import activate_proposal, make_proposal
    from jobagent.schemas.dynamic_rules import RuleConfirmation
    from tests.rules.test_dynamic_registry import request

    base = profile(BASE_VALUES)
    at = datetime(2026, 10, 2, tzinfo=UTC)
    original = owner_request(requested_at=at)
    change = request("TOP_PER_QUERY", 9)
    change.expected_version = base.version
    change.provenance.decided_at = at
    change.owner_request = original
    proposal = make_proposal(change, base, now=at)
    current = activate_proposal(proposal, RuleConfirmation(
        proposal_id=proposal.proposal_id, question_digest=proposal.question_digest,
        answer="Synthetic original approval", actor_id="synthetic owner", confirmed_at=at,
    ), base)
    result = prepare_configuration(
        preparation("owner_requested_change", owner_request=original), current,
        initialized=True, now=at,
    )
    assert not result.ask_user and result.questions == [] and result.status == "blocked_by_conflict"
