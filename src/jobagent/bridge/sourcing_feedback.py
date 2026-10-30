"""Explicit next-fetch consumption boundary; no polling and no platform access."""

from collections.abc import Sequence
from pathlib import Path

from jobagent.jobs.sourcing_feedback import build_feedback_strategy
from jobagent.schemas.sourcing_feedback import FeedbackSearchStrategy
from jobagent.storage.database import Database
from jobagent.storage.feedback_repository import SqliteFeedbackRepository


def next_fetch_strategy(
    database: Path, source: str, queries: Sequence[str], *, previous_version: str,
    candidate_id: str, actor_id: str,
) -> FeedbackSearchStrategy:
    """Called by the coordinator before an owner-requested fetch, not on a timer."""
    db = Database(database)
    db.migrate()
    repository = SqliteFeedbackRepository(db)
    plan = build_feedback_strategy(
        source, queries, repository.events(), previous=previous_version,
        candidate_id=candidate_id, actor_id=actor_id,
    )
    repository.save_strategy(plan)
    return plan
