"""Recompute small, reversible search hypotheses from private raw signals."""

import hashlib
import json

from jobagent.schemas.search_learning import (
    LearnedSearchPlan,
    SearchHypothesis,
    SearchLearningRequest,
    SearchSignal,
)


def learn_search(request: SearchLearningRequest) -> LearnedSearchPlan:
    """Return priorities only, without I/O, model calls, or changes to the input."""
    request = SearchLearningRequest.model_validate(request.model_dump())
    events = {event.event_id: event for event in request.signals}
    ordered = sorted(events.values(), key=lambda event: (event.occurred_at, event.event_id))
    latest: dict[tuple[str, str], SearchSignal] = {}
    for event in ordered:
        if event.owner_preference is not None:
            latest[(event.job.source, event.job.source_job_id)] = event
    features = sorted({term for event in latest.values() for term in event.features})
    hypotheses = []
    for feature in features:
        support = [event for event in latest.values()
                   if event.owner_preference == "like" and feature in event.features]
        counters = [event for event in latest.values() if feature in event.rejected_features]
        companies = {event.job.company.strip().casefold() for event in support}
        hypotheses.append(SearchHypothesis(
            feature=feature,
            status="contested" if counters else "active" if len(companies) >= 2 else "proposed",
            support_event_ids=sorted(event.event_id for event in support),
            counter_event_ids=sorted(event.event_id for event in counters),
            independent_companies=len(companies),
        ))
    baseline = list(dict.fromkeys(request.baseline_queries))
    active = [item.feature for item in sorted(
        hypotheses, key=lambda item: (-item.independent_companies, item.feature),
    ) if item.status == "active"]
    additions = [feature for feature in active if feature not in baseline][:2]
    preferred = [feature for feature in active if feature in baseline or feature in additions]
    payload = {
        "policy": "personal-ai-search-v2", "candidate_id": request.candidate_id,
        "baseline_queries": baseline,
        "signals": [events[key].model_dump(mode="json") for key in sorted(events)],
    }
    digest = hashlib.sha256(json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    return LearnedSearchPlan(
        candidate_id=request.candidate_id, version="sha256:" + digest,
        ordered_queries=preferred + [term for term in baseline if term not in preferred],
        hypotheses=hypotheses,
        source_event_ids=sorted(events),
    )
