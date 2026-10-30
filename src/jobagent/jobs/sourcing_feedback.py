"""Deterministic, explainable priority updates from explicit owner feedback."""

import hashlib
import json
from collections import defaultdict
from collections.abc import Sequence

from jobagent.errors import ContractValidationError
from jobagent.schemas.sourcing_feedback import FeedbackSearchStrategy, SourcingFeedback


def build_feedback_strategy(
    source: str, queries: Sequence[str], feedback: Sequence[SourcingFeedback], *, previous: str,
    candidate_id: str | None = None, actor_id: str | None = None,
) -> FeedbackSearchStrategy:
    """Reorder queries only after three distinct explicit direction declines.

    Candidate-bound three-way feedback affects a single job by default. Legacy
    events retain their reason-based drafting/collection split and query rules.
    No industry is excluded.
    """
    if (candidate_id is None) != (actor_id is None):
        raise ContractValidationError("Feedback scope requires both candidate and actor.")
    selected = [e for e in feedback if e.source == source]
    if candidate_id is None and any(e.candidate_id is not None for e in selected):
        raise ContractValidationError("Bound feedback requires explicit candidate/actor scope.")
    if candidate_id is not None:
        selected = [e for e in selected
                    if e.candidate_id == candidate_id and e.actor_id == actor_id]
    unique: dict[str, SourcingFeedback] = {}
    identities: dict[str, SourcingFeedback] = {}
    for event in selected:
        for existing in (unique.get(event.idempotency_key), identities.get(event.event_id)):
            if existing is not None and existing != event:
                raise ContractValidationError("Feedback identity conflict.")
        unique[event.idempotency_key] = event
        identities[event.event_id] = event
    events = sorted(unique.values(), key=lambda e: (e.occurred_at, e.event_id))
    query_order = list(dict.fromkeys(queries))
    direction_jobs: dict[str, set[str]] = defaultdict(set)
    deprioritized: set[str] = set()
    latest_preference = {
        e.job_id: e for e in events if e.action in {"approve", "revise"} or e.affects_sourcing
    }
    for event in latest_preference.values():
        if event.affects_sourcing:
            deprioritized.add(event.job_id)
        if (event.candidate_id is None and event.action == "decline"
                and event.reason_category == "direction"
                and event.free_text.strip() and event.search_term in query_order):
            direction_jobs[str(event.search_term)].add(event.job_id)
    penalties = {q: len(ids) for q, ids in direction_jobs.items() if len(ids) >= 3}
    ordered = sorted(query_order, key=lambda q: penalties.get(q, 0))
    applied = [e.event_id for e in latest_preference.values()
               if e.affects_sourcing or e.action in {"approve", "revise"}]
    payload = {"policy": "feedback-v2", "source": source,
               "candidate_id": candidate_id, "actor_id": actor_id, "baseline": query_order,
               "queries": ordered, "penalties": penalties,
               "jobs": sorted(deprioritized), "events": [e.model_dump(mode="json") for e in events]}
    version = "FETCH_" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:20].upper()
    return FeedbackSearchStrategy(
        version=version, previous_version=previous, source=source, ordered_queries=ordered,
        candidate_id=candidate_id, actor_id=actor_id,
        observed_feedback_ids=[e.event_id for e in events],
        query_penalties=penalties, deprioritized_job_ids=sorted(deprioritized),
        generator_feedback_ids=[e.event_id for e in events if (
            e.action == "revise" or (e.candidate_id is not None and e.action == "approve")
            or (e.candidate_id is None and e.action == "decline" and e.reason_category == "copy")
        )],
        collection_feedback_ids=[e.event_id for e in events
                                 if e.candidate_id is None and e.action == "decline"
                                 and e.reason_category == "facts"],
        applied_feedback_ids=applied,
        explanations=[
            "Only explicitly disliked postings receive individual priority reductions.",
            *[f"Query {q!r} moved later after {n} distinct direction declines."
              for q, n in penalties.items()],
            "Hard constraints, evidence, approvals and tool permissions remain unchanged.",
        ],
    )
