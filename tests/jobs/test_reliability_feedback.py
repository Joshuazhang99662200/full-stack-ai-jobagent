from datetime import UTC, datetime

import pytest

from jobagent.errors import ContractValidationError
from jobagent.jobs.sourcing_feedback import build_feedback_strategy
from jobagent.schemas.sourcing_feedback import SourcingFeedback


def event(candidate="CAND_ALPHA", actor="owner-alpha", event_id="event-one"):
    return SourcingFeedback(
        event_id=event_id, job_id="JOB_SYNTHETIC", source="boss",
        query_strategy_version="initial", action="decline", reason_category="job_dislike",
        content_digest="sha256:synthetic", actor_id=actor, candidate_id=candidate,
        occurred_at=datetime(2026, 10, 1, tzinfo=UTC), idempotency_key=event_id,
    )


def test_no_new_input_keeps_content_version_despite_parent_change():
    first = build_feedback_strategy("boss", ["Research"], [], previous="initial")
    second = build_feedback_strategy("boss", ["Research"], [], previous=first.version)
    assert first.version == second.version


def test_scoped_feedback_excludes_other_candidate_owner_and_legacy():
    events = [event(), event("CAND_OTHER", event_id="other"),
              event(actor="other-owner", event_id="other-owner"),
              event(None, event_id="legacy")]
    plan = build_feedback_strategy(
        "boss", ["Research"], events, previous="initial",
        candidate_id="CAND_ALPHA", actor_id="owner-alpha",
    )
    assert plan.applied_feedback_ids == ["event-one"]
    assert plan.candidate_id == "CAND_ALPHA" and plan.actor_id == "owner-alpha"


def test_bound_feedback_requires_explicit_scope():
    with pytest.raises(ContractValidationError, match="scope"):
        build_feedback_strategy("boss", ["Research"], [event()], previous="initial")


def test_conflicting_idempotency_keys_are_not_silently_overwritten():
    original = event(None)
    changed = original.model_copy(update={"action": "approve"})
    with pytest.raises(ContractValidationError, match="conflict"):
        build_feedback_strategy("boss", ["Research"], [original, changed], previous="initial")
