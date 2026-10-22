"""How strongly a posting speaks to the themes the person wants more of.

This orders postings within a match tier; it never changes a filter or match
decision, which stay grounded in the person's confirmed evidence.
"""

from collections.abc import Sequence

from jobagent.schemas.job_intelligence import PreferenceFactor


def preference_score(text: str, factors: Sequence[PreferenceFactor]) -> tuple[float, list[str]]:
    """The weighted share of factors whose terms appear in the text, and their names."""
    total = sum(factor.weight for factor in factors)
    if not total:
        return 0.0, []
    folded = text.casefold()
    hits = [f for f in factors if any(term.casefold() in folded for term in f.terms)]
    return round(sum(f.weight for f in hits) / total, 4), [f.name for f in hits]
