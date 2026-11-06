"""Feedback strategy and signal contract rules, independent of any host channel."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from jobagent.jobs.sourcing_feedback import build_feedback_strategy
from jobagent.schemas.sourcing_feedback import SourcingFeedback


def signal(action, *, eid, at, **updates):
    return SourcingFeedback(
        event_id=eid, job_id="JOB_FIXTURE", source="boss", search_term="Agent",
        query_strategy_version="v1", action=action, content_digest="sha256:fixture",
        actor_id="OWNER", occurred_at=at, idempotency_key=eid, candidate_id="CAND_TEST",
        original_text="Original greeting", revised_text="Revised greeting" if action == "revise"
        else None, jd_text="Build document agents.", job_title="Agent Product", company="Fixture",
        **updates,
    )


def test_revise_restores_jd_preference_and_tracks_negative_original_copy():
    now = datetime.now(UTC)
    old = signal("decline", eid="old", at=now)
    new = signal("revise", eid="new", at=now + timedelta(seconds=1))
    result = build_feedback_strategy("boss", ["Agent"], [old, new], previous="v1",
                                     candidate_id="CAND_TEST", actor_id="OWNER")
    assert not result.deprioritized_job_ids and result.generator_feedback_ids == ["new"]
    assert not result.query_penalties


def test_candidate_bound_decline_does_not_leak_into_copy_or_query_penalties():
    now = datetime.now(UTC)
    events = [
        signal("decline", eid=f"new{i}", at=now, reason_category="direction",
               free_text="This role is not suitable").model_copy(update={"job_id": f"JOB_{i}"})
        for i in range(3)
    ]
    result = build_feedback_strategy("boss", ["Agent", "AI"], events, previous="v1",
                                     candidate_id="CAND_TEST", actor_id="OWNER")
    assert result.query_penalties == {} and len(result.deprioritized_job_ids) == 3
    copy = signal("decline", eid="copy", at=now, reason_category="copy")
    result = build_feedback_strategy("boss", ["Agent"], [copy], previous="v1",
                                     candidate_id="CAND_TEST", actor_id="OWNER")
    assert result.generator_feedback_ids == [] and result.deprioritized_job_ids == ["JOB_FIXTURE"]


@pytest.mark.parametrize("field", ["candidate_id", "original_text", "revised_text", "jd_text"])
def test_revise_requires_bound_candidate_and_original_revision_jd_snapshot(field):
    data = signal("revise", eid="fixture", at=datetime.now(UTC)).model_dump()
    data[field] = None
    with pytest.raises(ValidationError):
        SourcingFeedback.model_validate(data)
