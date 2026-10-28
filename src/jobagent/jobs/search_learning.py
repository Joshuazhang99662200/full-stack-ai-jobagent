"""Recompute small, reversible search hypotheses from private raw signals."""

import hashlib
import json

from jobagent.errors import ContractValidationError
from jobagent.jobs.jd_snapshot import canonical_digest
from jobagent.jobs.lexicon import lexicon_digest
from jobagent.schemas.lexicon import JDFeatureSet, Lexicon, LexiconTerm, LexiconUpdateResult
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
        support = [
            event
            for event in latest.values()
            if event.owner_preference == "like" and feature in event.features
        ]
        counters = [event for event in latest.values() if feature in event.rejected_features]
        companies = {event.job.company.strip().casefold() for event in support}
        hypotheses.append(
            SearchHypothesis(
                feature=feature,
                status="contested" if counters else "active" if len(companies) >= 2 else "proposed",
                support_event_ids=sorted(event.event_id for event in support),
                counter_event_ids=sorted(event.event_id for event in counters),
                independent_companies=len(companies),
            )
        )
    baseline = list(dict.fromkeys(request.baseline_queries))
    active = [
        item.feature
        for item in sorted(
            hypotheses,
            key=lambda item: (-item.independent_companies, item.feature),
        )
        if item.status == "active"
    ]
    additions = [feature for feature in active if feature not in baseline][:2]
    preferred = [feature for feature in active if feature in baseline or feature in additions]
    payload = {
        "policy": "personal-ai-search-v2",
        "candidate_id": request.candidate_id,
        "baseline_queries": baseline,
        "signals": [events[key].model_dump(mode="json") for key in sorted(events)],
    }
    digest = hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return LearnedSearchPlan(
        candidate_id=request.candidate_id,
        version="sha256:" + digest,
        ordered_queries=preferred + [term for term in baseline if term not in preferred],
        hypotheses=hypotheses,
        source_event_ids=sorted(events),
    )


def latest_owner_signals(request: SearchLearningRequest) -> list[SearchSignal]:
    """Explicit latest job choices; message-only events never erase them."""
    validated = SearchLearningRequest.model_validate(request.model_dump())
    latest: dict[tuple[str, str], SearchSignal] = {}
    for event in sorted(validated.signals, key=lambda e: (e.occurred_at, e.event_id)):
        if event.owner_preference is not None:
            latest[(event.job.source, event.job.source_job_id)] = event
    return sorted(latest.values(), key=lambda e: e.event_id)


def rebuild_lexicon(
    lexicon: Lexicon,
    feature_sets: list[JDFeatureSet],
    request: SearchLearningRequest,
) -> LexiconUpdateResult:
    """Absolute, replayable statistics and owner-only soft weights; no I/O."""
    choices = latest_owner_signals(request)
    latest: dict[str, JDFeatureSet] = {}
    for value in feature_sets:
        previous = latest.get(value.job_id)
        if previous is None or value.snapshot_version > previous.snapshot_version:
            latest[value.job_id] = value
        elif value.snapshot_version == previous.snapshot_version and value != previous:
            raise ContractValidationError("Choose one reviewed feature version per JD snapshot.")
    snapshots = sorted(latest.values(), key=lambda value: value.job_id)
    full = [value for value in snapshots if value.completeness == "full"]
    policy_terms = [
        term.model_dump(
            mode="json",
            exclude={
                "count",
                "last_seen",
                "source_refs",
                "preference_weight",
                "independent_companies",
                "maturity",
            },
        )
        for term in lexicon.terms
        if term.source == "人工" or term.aliases or term.weight != 1.0 or term.seed
    ]
    evidence_input = [
        {
            "snapshot_id": value.snapshot_id,
            "job_id": value.job_id,
            "snapshot_version": value.snapshot_version,
            "jd_text_hash": value.jd_text_hash,
            "company": value.company,
            "fetched_at": None if value.fetched_at is None else value.fetched_at.isoformat(),
            "completeness": value.completeness,
            "features": [f.model_dump(mode="json") for f in value.features],
        }
        for value in snapshots
    ]
    owner_input = [value.model_dump(mode="json", exclude={"message_feedback"}) for value in choices]
    derivation = canonical_digest(
        {
            "policy": "jd-lexicon-v1",
            "candidate_id": request.candidate_id,
            "domain": lexicon.domain,
            "policy_terms": policy_terms,
            "combinations": lexicon.combinations,
            "snapshots": evidence_input,
            "owner": owner_input,
        }
    )
    event_ids = sorted({e.event_id for e in request.signals})
    ignored = sorted({e.event_id for e in request.signals if e.owner_preference is None})
    if not snapshots and not choices:
        return LexiconUpdateResult(
            lexicon=lexicon,
            version_digest=lexicon_digest(lexicon),
            changed=False,
            source_event_ids=event_ids,
            ignored_event_ids=ignored,
        )
    known = {(term.dimension, term.term.casefold()): term for term in lexicon.terms}
    for value in full:
        for feature in value.features:
            key = (feature.dimension, feature.term.casefold())
            if key not in known:
                known[key] = LexiconTerm(dimension=feature.dimension, term=feature.term)
    if len(known) > 200:
        raise ContractValidationError("Lexicon candidate limit reached; review the private scope.")
    hypotheses = {h.feature.casefold(): h for h in learn_search(request).hypotheses}
    terms = []
    for key, term in known.items():
        evidence = [
            value
            for value in full
            if any(
                (feature.dimension, feature.term.casefold()) == key
                and feature.polarity == "positive"
                for feature in value.features
            )
        ]
        companies = {value.company.strip().casefold() for value in evidence if value.company}
        hypothesis = hypotheses.get(term.term.casefold())
        bonus = (
            min(0.2, 0.05 * hypothesis.independent_companies)
            if (hypothesis is not None and hypothesis.status == "active")
            else 0.0
        )
        seen_dates = [value.fetched_at.date() for value in evidence if value.fetched_at is not None]
        count = len(evidence)
        maturity = (
            "stable"
            if len(companies) >= 3
            else ("repeated" if len(companies) >= 2 else "observed_once")
        )
        terms.append(
            LexiconTerm.model_validate(
                {
                    **term.model_dump(),
                    "count": count,
                    "last_seen": max(seen_dates) if seen_dates else None,
                    "source_refs": sorted(value.snapshot_id for value in evidence),
                    "independent_companies": len(companies),
                    "maturity": maturity,
                    "preference_weight": bonus,
                }
            )
        )
    changed = derivation != lexicon.derivation_digest
    dates = [lexicon.updated_at]
    dates.extend(value.fetched_at.date() for value in snapshots if value.fetched_at is not None)
    dates.extend(value.occurred_at.date() for value in choices)
    result = Lexicon.model_validate(
        {
            **lexicon.model_dump(),
            "terms": [term.model_dump() for term in terms],
            "based_on_snapshots": len(full),
            "based_on_feedback_events": len(choices),
            "updated_at": max(dates),
            "derivation_digest": derivation,
            "feedback_event_ids": sorted(value.event_id for value in choices),
            "snapshot_ids": sorted(value.snapshot_id for value in full),
            "lexicon_version": "v" + str(int(lexicon.lexicon_version[1:]) + 1)
            if changed
            else lexicon.lexicon_version,
            "parent_digest": lexicon_digest(lexicon) if changed else lexicon.parent_digest,
        }
    )
    return LexiconUpdateResult(
        lexicon=result,
        version_digest=lexicon_digest(result),
        changed=changed,
        source_event_ids=event_ids,
        ignored_event_ids=ignored,
    )
