import pytest
from pydantic import ValidationError

from jobagent.schemas.jobs import FilterDecision, HardFilterResult, MatchDecision, MatchResult


def test_reject_requires_deterministic_reasons() -> None:
    with pytest.raises(ValidationError):
        HardFilterResult(decision=FilterDecision.REJECT, reasons=[])


def test_match_requires_explanation_not_only_score() -> None:
    with pytest.raises(ValidationError):
        MatchResult(overall=0.86, decision=MatchDecision.STRONG_MATCH)
