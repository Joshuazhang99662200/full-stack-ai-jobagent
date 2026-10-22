"""Derive read-only search terms from a candidate's confirmed knowledge base.

This is deterministic term selection, not fact generation. Every emitted term is
already present in the profile and is backed by confirmed evidence, so searching
can never introduce a claim the candidate has not confirmed.
"""

import re
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


def _most_recent_first(profile: CandidateProfile) -> list[Experience]:
    def sort_key(experience: Experience) -> tuple[int, str]:
        start = experience.time_range.start
        return (0 if start is None else 1, "" if start is None else start.isoformat())

    return sorted(profile.experiences, key=sort_key, reverse=True)


def _evidence_text(item: EvidenceItem) -> str:
    return " ".join([item.statement, *item.skills, *item.domains]).casefold()
