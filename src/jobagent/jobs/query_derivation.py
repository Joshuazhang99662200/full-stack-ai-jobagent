"""Derive read-only search terms from a candidate's confirmed knowledge base.

This is deterministic term selection, not fact generation. Every emitted term is
already present in the profile and is backed by confirmed evidence, so searching
can never introduce a claim the candidate has not confirmed.
"""

from collections.abc import Sequence

from jobagent.schemas.candidate import CandidateProfile, EvidenceItem, Experience
from jobagent.schemas.job_intelligence import (
    JobSearchQuery,
    SearchQuerySuggestion,
    SearchQuerySuggestionSet,
    SearchTermOrigin,
)

# Ordered strongest-signal-first; ties inside a tier break on support count.
_ORIGIN_RANK = {
    SearchTermOrigin.HEADLINE: 0,
    SearchTermOrigin.RECENT_TITLE: 1,
    SearchTermOrigin.SKILL: 2,
}


# Headlines are positioning statements ("role · credential · pitch"), so only the
# leading segment is a usable search keyword.
# Fullwidth variants are intentional: headlines are frequently written in Chinese.
_HEADLINE_SEPARATORS = "·|｜/、,，;；"  # noqa: RUF001


def _normalized(value: str) -> str:
    return " ".join(value.split()).casefold()


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
            if origin is not SearchTermOrigin.HEADLINE and not supporting:
                # Only the headline may stand without a direct evidence link; it is
                # the candidate's own positioning rather than a factual claim.
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

        add(_headline_term(profile.headline), SearchTermOrigin.HEADLINE, ())

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


def _most_recent_first(profile: CandidateProfile) -> list[Experience]:
    def sort_key(experience: Experience) -> tuple[int, str]:
        start = experience.time_range.start
        return (0 if start is None else 1, "" if start is None else start.isoformat())

    return sorted(profile.experiences, key=sort_key, reverse=True)
