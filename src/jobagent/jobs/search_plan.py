"""Which search terms a board should run next.

Most slots rotate through the configured terms, oldest search first, so every
term gets its turn; one slot goes to the term whose past searches turned up the
most jobs that later matched strong or possible. A term never searched on a
board goes first. The plan reads history only; it decides nothing about jobs.
"""

from collections.abc import Mapping, Sequence

from jobagent.schemas.job_intelligence import JobSearchHit, SearchPlan, SearchRun, SearchTermStat

PROMISING_TIERS = frozenset({"strong_match", "possible_match"})


def _stats(
    term: str,
    source: str,
    runs: Sequence[SearchRun],
    hits: Sequence[JobSearchHit],
    tiers: Mapping[str, str],
) -> SearchTermStat:
    mine = [r for r in runs if r.source == source and r.search_term == term]
    found = {h.job_id for h in hits if h.source == source and h.search_term == term}
    return SearchTermStat(
        term=term,
        searches=len(mine),
        results=sum(r.results for r in mine),
        new=sum(r.new for r in mine),
        hits=len(found),
        promising=sum(tiers.get(job_id) in PROMISING_TIERS for job_id in found),
        last_searched=max((r.searched_at for r in mine), default=None),
    )


def plan_searches(
    terms: Sequence[str],
    source: str,
    *,
    runs: Sequence[SearchRun],
    hits: Sequence[JobSearchHit],
    tiers: Mapping[str, str],
    per_site: int,
) -> SearchPlan:
    unique = list(dict.fromkeys(t.strip() for t in terms if t.strip()))
    stats = [_stats(term, source, runs, hits, tiers) for term in unique]
    order = {s.term: index for index, s in enumerate(stats)}

    def staleness(stat: SearchTermStat) -> tuple[bool, float, int]:
        # Never searched sorts first; then oldest search; config order breaks ties.
        when = stat.last_searched.timestamp() if stat.last_searched else 0.0
        return (stat.last_searched is not None, when, order[stat.term])

    rotation = sorted(stats, key=staleness)
    rotation_slots = max(1, per_site - 1)
    chosen = rotation[:rotation_slots]
    best = sorted(
        (s for s in stats if s.promising and s not in chosen),
        key=lambda s: (-s.promising, order[s.term]),
    )
    for stat in best + [s for s in rotation if s not in chosen]:
        if len(chosen) >= per_site:
            break
        if stat not in chosen:
            chosen.append(stat)
    return SearchPlan(source=source, chosen=chosen[:per_site], stats=stats)
