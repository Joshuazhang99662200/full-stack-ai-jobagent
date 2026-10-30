from datetime import UTC, datetime


def test_copy_decline_never_changes_fetch_queries_or_job_priority() -> None:
    from jobagent.jobs.sourcing_feedback import build_feedback_strategy
    from jobagent.schemas.sourcing_feedback import SourcingFeedback

    feedback = SourcingFeedback(
        event_id="ev_copy", job_id="JOB_ALPHA", source="boss", search_term="Agent",
        query_strategy_version="v1", action="decline", reason_category="copy",
        content_digest="sha256:example", actor_id="ou_owner", occurred_at=datetime.now(UTC),
        idempotency_key="ev_copy",
    )
    plan = build_feedback_strategy("boss", ["Agent", "AI产品经理"], [feedback], previous="v1")
    assert plan.ordered_queries == ["Agent", "AI产品经理"]
    assert plan.deprioritized_job_ids == [] and plan.query_penalties == {}
    assert plan.generator_feedback_ids == ["ev_copy"]


def test_single_job_dislike_does_not_exclude_industry_or_search_term() -> None:
    from jobagent.jobs.sourcing_feedback import build_feedback_strategy
    from jobagent.schemas.sourcing_feedback import SourcingFeedback

    feedback = SourcingFeedback(
        event_id="ev_dislike", job_id="JOB_ALPHA", source="boss", search_term="Agent",
        query_strategy_version="v1", action="decline", reason_category="job_dislike",
        content_digest="sha256:example", actor_id="ou_owner", occurred_at=datetime.now(UTC),
        idempotency_key="ev_dislike",
    )
    plan = build_feedback_strategy("boss", ["Agent", "AI产品经理"], [feedback], previous="v1")
    assert plan.deprioritized_job_ids == ["JOB_ALPHA"]
    assert plan.ordered_queries == ["Agent", "AI产品经理"] and plan.query_penalties == {}
    assert plan.previous_version == "v1" and plan.version != "v1"


def test_repeated_explicit_direction_feedback_reorders_but_never_removes_queries() -> None:
    from jobagent.jobs.sourcing_feedback import build_feedback_strategy
    from jobagent.schemas.sourcing_feedback import SourcingFeedback

    events = [SourcingFeedback(
        event_id=f"ev_{i}", job_id=f"JOB_{i}", source="boss", search_term="旧方向",
        query_strategy_version="v1", action="decline", reason_category="direction",
        free_text="不喜欢这个产品方向", content_digest="sha256:example", actor_id="ou_owner",
        occurred_at=datetime.now(UTC), idempotency_key=f"ev_{i}",
    ) for i in range(3)]
    plan = build_feedback_strategy("boss", ["旧方向", "Agent"], events, previous="v1")
    assert plan.ordered_queries == ["Agent", "旧方向"]
    assert plan.query_penalties == {"旧方向": 3} and len(plan.deprioritized_job_ids) == 3


def test_later_explicit_approval_supersedes_that_job_dislike() -> None:
    from datetime import timedelta

    from jobagent.jobs.sourcing_feedback import build_feedback_strategy
    from jobagent.schemas.sourcing_feedback import SourcingFeedback

    now = datetime.now(UTC)
    old = SourcingFeedback(
        event_id="old", job_id="JOB_A", source="boss", search_term="Agent",
        query_strategy_version="v1", action="decline", reason_category="job_dislike",
        content_digest="sha256:example", actor_id="owner", occurred_at=now, idempotency_key="old",
    )
    new = old.model_copy(update={
        "event_id": "new", "idempotency_key": "new", "action": "approve",
        "occurred_at": now + timedelta(seconds=1),
    })
    result = build_feedback_strategy("boss", ["Agent"], [old, new], previous="v1")
    assert result.deprioritized_job_ids == []
