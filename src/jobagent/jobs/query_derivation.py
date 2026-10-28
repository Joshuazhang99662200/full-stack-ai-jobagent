"""Derive read-only search terms from a candidate's confirmed knowledge base.

This is deterministic term selection, not fact generation. Every emitted term is
already present in the profile and is backed by confirmed evidence, so searching
can never introduce a claim the candidate has not confirmed.
"""

import re
from collections.abc import Sequence
from datetime import datetime
from itertools import product

from jobagent.errors import ContractValidationError
from jobagent.jobs.jd_snapshot import canonical_digest
from jobagent.jobs.lexicon import lexicon_digest
from jobagent.jobs.search_learning import latest_owner_signals, rebuild_lexicon
from jobagent.schemas.candidate import CandidateProfile, EvidenceItem, Experience
from jobagent.schemas.job_intelligence import (
    JobSearchQuery,
    SearchQuerySuggestion,
    SearchQuerySuggestionSet,
    SearchTermOrigin,
)
from jobagent.schemas.lexicon import (
    CombinationPlan,
    CombinationQuery,
    CombinationRequest,
    Lexicon,
    LexiconTerm,
)
from jobagent.schemas.search_learning import SearchLearningRequest, SearchSignal

# Ordered strongest-signal-first; ties inside a tier break on support count.
_ORIGIN_RANK = {
    SearchTermOrigin.TARGET_ROLE: 0,
    SearchTermOrigin.TARGET_VARIANT: 1,
    SearchTermOrigin.HEADLINE: 2,
    SearchTermOrigin.RECENT_TITLE: 3,
    SearchTermOrigin.SKILL: 4,
}

# Job boards title AI product roles with these qualifiers. A qualifier is offered
# only when confirmed evidence mentions one of its cues, so a variant never claims
# a direction the candidate has no record in.
_ROLE_QUALIFIERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Agent", ("agent", "智能体")),
    ("Skill", ("skill",)),
    ("大模型", ("大模型", "llm")),
    ("AI", ("ai", "人工智能")),
)

_CJK = r"[\u3400-\u9fff]"
_TRAILING_CJK = re.compile(rf"{_CJK}+$")


# Headlines are positioning statements ("role · credential · pitch"), so only the
# leading segment is a usable search keyword.
# Fullwidth variants are intentional: headlines are frequently written in Chinese.
_HEADLINE_SEPARATORS = "·|｜/、,，;；"  # noqa: RUF001


def _normalized(value: str) -> str:
    return " ".join(value.split()).casefold()


def _compact(term: str) -> str:
    """Drop the spaces boards treat as separators next to Chinese text."""
    collapsed = " ".join(term.split())
    return re.sub(rf"\s+(?={_CJK})|(?<={_CJK})\s+", "", collapsed)


def _role_noun(target: str) -> str | None:
    match = _TRAILING_CJK.search(_compact(target))
    return match.group(0) if match else None


def _headline_term(headline: str | None) -> str | None:
    if headline is None:
        return None
    segment = headline
    for separator in _HEADLINE_SEPARATORS:
        segment = segment.split(separator)[0]
    segment = segment.strip()
    return segment or None


class SearchQueryDeriver:
    """Turn confirmed candidate knowledge into ranked, explainable search terms."""

    def __init__(self, *, max_suggestions: int = 10) -> None:
        self._max_suggestions = max_suggestions

    def derive(
        self,
        profile: CandidateProfile,
        evidence: Sequence[EvidenceItem],
        *,
        location: str | None = None,
        target_roles: Sequence[str] = (),
    ) -> SearchQuerySuggestionSet:
        confirmed = {item.id: item for item in evidence if item.user_confirmed}
        skipped = len(evidence) - len(confirmed)

        collected: list[SearchQuerySuggestion] = []
        seen: set[str] = set()

        def add(term: str | None, origin: SearchTermOrigin, evidence_ids: Sequence[str]) -> None:
            if term is None or not term.strip():
                return
            key = _normalized(term)
            if key in seen:
                return
            supporting = sorted(item for item in evidence_ids if item in confirmed)
            stated_by_candidate = origin in (
                SearchTermOrigin.HEADLINE,
                SearchTermOrigin.TARGET_ROLE,
            )
            if not stated_by_candidate and not supporting:
                # Only the headline and a stated target may stand without a direct
                # evidence link; they are the candidate's own positioning.
                return
            seen.add(key)
            collected.append(
                SearchQuerySuggestion(
                    term=term.strip(),
                    origin=origin,
                    support_count=len(supporting),
                    supporting_evidence_ids=supporting,
                    query=JobSearchQuery(query=term.strip(), location=location),
                )
            )

        targets = [_compact(target) for target in target_roles if target.strip()]
        for target in targets:
            add(target, SearchTermOrigin.TARGET_ROLE, ())
        for noun in dict.fromkeys(noun for t in targets if (noun := _role_noun(t))):
            for qualifier, cues in _ROLE_QUALIFIERS:
                backing = [
                    item.id
                    for item in confirmed.values()
                    if any(cue in _evidence_text(item) for cue in cues)
                ]
                add(f"{qualifier}{noun}", SearchTermOrigin.TARGET_VARIANT, backing)

        add(_headline_term(profile.headline), SearchTermOrigin.HEADLINE, ())

        if not targets:
            # A stated target replaces backward-looking titles and bare skill names:
            # neither is a title the candidate is now looking for.
            for experience in _most_recent_first(profile):
                add(experience.title, SearchTermOrigin.RECENT_TITLE, experience.evidence_ids)
            for skill in profile.skills:
                add(skill.name, SearchTermOrigin.SKILL, skill.evidence_ids)

        collected.sort(key=lambda item: (_ORIGIN_RANK[item.origin], -item.support_count, item.term))
        return SearchQuerySuggestionSet(
            candidate_id=profile.id,
            suggestions=collected[: self._max_suggestions],
            skipped_unconfirmed_evidence_count=skipped,
        )

    def derive_combinations(self, lexicon: Lexicon, request: CombinationRequest) -> CombinationPlan:
        """Generate bounded combinations with verifiable sources, rotation and cooldown."""
        learning = request.learning or SearchLearningRequest(
            candidate_id=request.candidate_id,
            baseline_queries=request.baseline_queries,
        )
        compiled = rebuild_lexicon(lexicon, request.feature_sets, learning).lexicon
        stats = {(t.dimension, t.term.casefold()): t for t in compiled.terms}
        pools: dict[str, list[LexiconTerm]] = {}
        for term in lexicon.terms:
            measured = stats[(term.dimension, term.term.casefold())]
            if term.dimension not in {"domain", "scenario", "tech", "role"} or term.weight <= 0:
                continue
            if not term.seed and measured.independent_companies < 2:
                continue
            pools.setdefault(term.dimension, []).append(measured)
        if any(len(pool) > 20 for pool in pools.values()):
            raise ContractValidationError("Too many eligible terms in one facet; narrow the scope.")
        penalties: dict[str, list[SearchSignal]] = {}
        for event in latest_owner_signals(learning):
            if (
                event.owner_preference == "dislike"
                and event.rejection_reason == "direction"
                and event.query_term is not None
                and event.job.source == request.source
            ):
                penalties.setdefault(event.query_term, []).append(event)
        candidates: dict[str, CombinationQuery] = {}
        priority: dict[str, int] = {}
        for tier, template in enumerate(lexicon.combinations):
            dimensions = re.findall(r"\{([a-z_]+)\}", template)
            if any(dimension not in pools for dimension in dimensions):
                continue
            for combination_terms in product(*(pools[dimension] for dimension in dimensions)):
                components = {term.dimension: term.term for term in combination_terms}
                query = " ".join(term.term for term in combination_terms)
                if len(query) > 200:
                    raise ContractValidationError("A combination exceeds the query contract.")
                if query in candidates:
                    continue
                negatives = penalties.get(query, [])
                companies = {e.job.company.strip().casefold() for e in negatives}
                demoted = len(negatives) >= 3 and len(companies) >= 3
                common = set.intersection(*(set(term.source_refs) for term in combination_terms))
                weight = sum(
                    term.weight * (1 + term.preference_weight) for term in combination_terms
                ) / len(combination_terms)
                reason = (
                    "manual_seed"
                    if all(term.seed for term in combination_terms)
                    else ("independent_snapshot_repetition")
                )
                if not common:
                    reason += "; cooccurrence_not_observed"
                if demoted:
                    reason += "; three_independent_direction_rejections"
                candidates[query] = CombinationQuery(
                    query=query,
                    combination=components,
                    weight=weight,
                    reason=reason,
                    source=lexicon.lexicon_version + "/" + lexicon_digest(lexicon),
                    snapshot_ids=sorted(common),
                    demoted=demoted,
                    feedback_event_ids=sorted(e.event_id for e in negatives) if demoted else [],
                )
                priority[query] = tier
                if len(candidates) > 256:
                    raise ContractValidationError(
                        "Combination limit reached; narrow the private scope."
                    )
        last: dict[str, datetime] = {}
        for run in request.history:
            if run.source == request.source:
                if run.searched_at.tzinfo is None:
                    raise ContractValidationError("Query history needs timezone-aware timestamps.")
                last[run.search_term] = max(
                    last.get(run.search_term, run.searched_at), run.searched_at
                )

        def order(query: CombinationQuery) -> tuple[bool, bool, float, float, int, str]:
            previous = last.get(query.query)
            return (
                query.demoted,
                previous is not None,
                previous.timestamp() if previous is not None else 0.0,
                -query.weight,
                priority[query.query],
                query.query,
            )

        ranked = sorted(candidates.values(), key=order)
        ready = [
            query
            for query in ranked
            if query.query not in last
            or (request.now - last[query.query]).total_seconds() >= request.cooldown_hours * 3600
        ]
        chosen = ready[: request.query_limit]
        chosen_names = {query.query for query in chosen}
        return CombinationPlan(
            candidate_id=request.candidate_id,
            source=request.source,
            version=canonical_digest(
                {
                    "policy": "combination-v1",
                    "lexicon": lexicon_digest(lexicon),
                    "request": request.model_dump(mode="json"),
                }
            ),
            lexicon_version=lexicon.lexicon_version,
            status="ready" if chosen else "cooldown" if ranked else "needs_seed",
            ordered_queries=chosen,
            deferred_queries=[query for query in ranked if query.query not in chosen_names],
            fallback_queries=request.baseline_queries[: request.query_limit] if not ranked else [],
        )


def _most_recent_first(profile: CandidateProfile) -> list[Experience]:
    def sort_key(experience: Experience) -> tuple[int, str]:
        start = experience.time_range.start
        return (0 if start is None else 1, "" if start is None else start.isoformat())

    return sorted(profile.experiences, key=sort_key, reverse=True)


def _evidence_text(item: EvidenceItem) -> str:
    return " ".join([item.statement, *item.skills, *item.domains]).casefold()
