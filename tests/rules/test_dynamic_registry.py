from datetime import UTC, datetime

import pytest

from jobagent.errors import ContractValidationError


def request(name="ABANDON_HOURS", value=72):
    from jobagent.schemas.dynamic_rules import RuleChangeRequest, RuleProvenance

    return RuleChangeRequest(
        candidate_id="CAND_SYNTHETIC",
        name=name,
        value=value,
        expected_version=None,
        provenance=RuleProvenance(
            source_kind="user",
            source_ref="synthetic owner message",
            decided_at=datetime(2026, 10, 1, tzinfo=UTC),
            decided_by="synthetic owner",
        ),
    )


def test_registry_rejects_unknown_names_and_invalid_numeric_types():
    from jobagent.rules.registry import validate_change

    for name, value in [
        ("ARBITRARY_CODE", "run()"),
        ("ABANDON_HOURS", True),
        ("ABANDON_HOURS", 0),
        ("GREETING_LEN_SHORT", [200, 100]),
        ("POLL_ALIGN_MINUTE", "not-a-time"),
    ]:
        with pytest.raises(ContractValidationError):
            validate_change(request(name, value))


@pytest.mark.parametrize(
    "name,value",
    [
        ("LIEPIN_API_RATE_PER_MIN", 100),
        ("LIEPIN_TOKEN_VALIDITY_DAYS", 120),
        ("QUEUE_TOTAL_SYNTHETIC_SNAPSHOT", 100),
        ("QUEUE_SYNTHETIC_FEEDBACK_HOLD", "release"),
        ("GATE_POINT_MODE", "automatic"),
        ("LIEPIN_DELIVERY_PARALLEL", 5),
    ],
)
def test_references_observations_and_safety_are_not_user_tuning(name, value):
    from jobagent.rules.registry import validate_change

    with pytest.raises(ContractValidationError):
        validate_change(request(name, value))


def test_host_guess_is_not_confirmable_as_owner_decision():
    from jobagent.rules.registry import validate_change

    change = request("MCP_BATCHSIZE", 4)
    change.provenance.source_kind = "host_proposal"
    with pytest.raises(ContractValidationError, match="user"):
        validate_change(change)


def test_rule_proposal_and_activation_change_only_named_variable():
    from jobagent.rules.service import activate_proposal, make_proposal
    from jobagent.schemas.dynamic_rules import RuleConfirmation

    now = datetime(2026, 10, 1, tzinfo=UTC)
    first = make_proposal(request(), None, now=now)
    confirmation = RuleConfirmation(
        proposal_id=first.proposal_id,
        question_digest=first.question_digest,
        answer="Synthetic owner approves this exact change.",
        actor_id="synthetic owner",
        confirmed_at=now,
    )
    snapshot = activate_proposal(first, confirmation, None)
    assert snapshot.values == {"ABANDON_HOURS": 72}
    next_request = request("PENDING_BACKLOG_ASK_THRESHOLD", 12)
    next_request.expected_version = snapshot.version
    proposal = make_proposal(next_request, snapshot, now=now)
    changed = activate_proposal(
        proposal,
        confirmation.model_copy(
            update={
                "proposal_id": proposal.proposal_id,
                "question_digest": proposal.question_digest,
            }
        ),
        snapshot,
    )
    assert changed.values == {"ABANDON_HOURS": 72, "PENDING_BACKLOG_ASK_THRESHOLD": 12}
    assert snapshot.values == {"ABANDON_HOURS": 72}
    with pytest.raises(ContractValidationError):
        activate_proposal(proposal, confirmation, snapshot)


def test_new_change_cannot_be_effective_before_current_version():
    from datetime import timedelta

    from jobagent.rules.service import make_proposal
    from tests.rules.test_evaluation import profile

    current = profile({"ABANDON_HOURS": 72})
    change = request("PENDING_BACKLOG_ASK_THRESHOLD", 5)
    change.expected_version = current.version
    change.provenance.decided_at = current.effective_at - timedelta(seconds=2)
    with pytest.raises(ContractValidationError, match="time"):
        make_proposal(change, current, now=current.effective_at - timedelta(seconds=1))


def test_older_owner_decision_cannot_replace_newer_value():
    from datetime import timedelta

    from jobagent.rules.service import make_proposal
    from tests.rules.test_evaluation import profile

    current = profile({"ABANDON_HOURS": 72})
    change = request("ABANDON_HOURS", 84)
    change.expected_version = current.version
    change.provenance.decided_at = current.provenance["ABANDON_HOURS"].decided_at - timedelta(
        days=1
    )
    with pytest.raises(ContractValidationError, match="decision"):
        make_proposal(change, current, now=current.effective_at + timedelta(days=1))


def test_confirmation_actor_matches_declared_owner():
    from jobagent.rules.service import activate_proposal, make_proposal
    from jobagent.schemas.dynamic_rules import RuleConfirmation

    at = datetime(2026, 10, 1, tzinfo=UTC)
    proposed = make_proposal(request(), None, now=at)
    with pytest.raises(ContractValidationError, match="owner"):
        activate_proposal(
            proposed,
            RuleConfirmation(
                proposal_id=proposed.proposal_id,
                question_digest=proposed.question_digest,
                answer="Synthetic approval",
                actor_id="another actor",
                confirmed_at=at,
            ),
            None,
        )
