from datetime import UTC, datetime, timedelta

import pytest

from jobagent.errors import ContractValidationError
from jobagent.rules.service import make_proposal, validate_snapshot
from jobagent.schemas.dynamic_rules import RuleConfirmation
from tests.rules.test_dynamic_registry import request
from tests.rules.test_evaluation import profile
from tests.rules.test_preparation import BASE_VALUES, owner_request

NOW = datetime(2026, 10, 3, tzinfo=UTC)


def confirmed(base, name="TOP_PER_QUERY", value=4, *, run_id="SYNTH_ROUND"):
    from jobagent.schemas.sourcing import ConfirmedRoundOverride

    change = request(name, value)
    change.expected_version = base.version
    change.provenance.decided_at = NOW
    change.owner_request = owner_request(
        names=[name], scope="round", run_id=run_id, requested_at=NOW,
    )
    proposal = make_proposal(change, base, now=NOW)
    return ConfirmedRoundOverride(proposal=proposal, confirmation=RuleConfirmation(
        proposal_id=proposal.proposal_id, question_digest=proposal.question_digest,
        answer="Synthetic exact round-only approval", actor_id="synthetic owner",
        confirmed_at=NOW + timedelta(seconds=1),
    ))


def test_round_overlay_aggregates_independent_confirmations_without_mutating_reusable_base():
    from jobagent.rules.rounds import apply_round_overrides

    base = profile(BASE_VALUES)
    before = base.model_dump(mode="json")
    overrides = [confirmed(base), confirmed(base, "DETAIL_ATTEMPTS_PER_SITE_PER_ROUND", 11)]
    result = apply_round_overrides(base, overrides, run_id="SYNTH_ROUND",
                                   now=NOW + timedelta(seconds=2))
    assert result.values["TOP_PER_QUERY"] == 4
    assert result.values["DETAIL_ATTEMPTS_PER_SITE_PER_ROUND"] == 11
    assert result.values["DETAIL_CAP_PER_DAY"] == 37
    assert result.parent_version == base.version and result.version != base.version
    assert base.model_dump(mode="json") == before
    assert validate_snapshot(result) == result
    reverse = apply_round_overrides(base, list(reversed(overrides)), run_id="SYNTH_ROUND",
                                    now=NOW + timedelta(seconds=2))
    assert reverse == result
    assert apply_round_overrides(base, [], run_id="OTHER_ROUND", now=NOW) == base


@pytest.mark.parametrize("kind", [
    "different_run", "duplicate", "forged_question", "late_confirmation", "wrong_actor",
    "reusable_scope", "different_candidate", "stale_base",
])
def test_invalid_round_approval_is_rejected(kind):
    from jobagent.rules.rounds import apply_round_overrides

    base = profile(BASE_VALUES)
    entry = confirmed(base)
    clock = NOW + timedelta(seconds=2)
    target = "SYNTH_ROUND"
    entries = [entry]
    if kind == "different_run":
        target = "OTHER_ROUND"
    elif kind == "duplicate":
        entries.append(entry)
    elif kind == "forged_question":
        entry.proposal.question += " forged"
    elif kind == "late_confirmation":
        clock = NOW
    elif kind == "wrong_actor":
        entry.confirmation.actor_id = "another actor"
    elif kind == "reusable_scope":
        entry.proposal.request.owner_request = entry.proposal.request.owner_request.model_copy(
            update={"scope": "reusable", "run_id": None},
        )
    elif kind == "different_candidate":
        base = profile(BASE_VALUES, candidate_id="CAND_OTHER")
    elif kind == "stale_base":
        base = profile(BASE_VALUES | {"PENDING_BACKLOG_ASK_THRESHOLD": 5})
    with pytest.raises(ContractValidationError):
        apply_round_overrides(base, entries, run_id=target, now=clock)
