# ruff: noqa: RUF001  -- Chinese greetings carry full-width punctuation by design.
"""Deterministic checks for a first greeting.

The wording rules live in references/message-generation.md ("首条招呼"); this module
enforces the parts of them a machine can check exactly: numbers and banned
phrases. Anything it cannot check stays with the person who approves the batch.
"""

import re

# The only places a number may appear: "0 到 1" phrasing, and a title in 《》.
_ALLOWED_NUMBER_SPANS = (re.compile(r"0\s*到\s*1"), re.compile(r"《[^》]*》"))
_ANY_DIGIT = re.compile(r"[0-9０-９]")

BANNED_PHRASES = ("修订率", "HITL", "智能体协作", "很感兴趣", "期待交流", "既懂")


def first_greeting_problems(text: str) -> list[str]:
    """Check content; full-message writing has no repository character ceiling."""
    problems: list[str] = []
    stripped = text
    for allowed in _ALLOWED_NUMBER_SPANS:
        stripped = allowed.sub("", stripped)
    if _ANY_DIGIT.search(stripped):
        problems.append("contains_number")
    folded = text.casefold()
    problems.extend(
        f"banned_phrase:{phrase}" for phrase in BANNED_PHRASES if phrase.casefold() in folded
    )
    return problems
