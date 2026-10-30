"""Evidence-bound edit spans. Semantic categories remain host/user proposals."""

from difflib import SequenceMatcher
from typing import get_args

from jobagent.jobs.jd_snapshot import text_digest
from jobagent.jobs.job_intake import reject
from jobagent.schemas.message_diff import (
    DiffCategory,
    DiffSpan,
    MessageDiffInput,
    MessageDiffResult,
)

CATEGORIES: tuple[DiffCategory, ...] = get_args(DiffCategory)


def overlaps(start: int, end: int, left: int, right: int) -> bool:
    if start == end or left == right:
        return start <= left <= end or left <= start <= right
    return max(start, left) < min(end, right)


def compare(request: MessageDiffInput) -> MessageDiffResult:
    if (text_digest(request.initial_text), text_digest(request.final_text)) != (
        request.initial_hash,
        request.final_hash,
    ):
        reject("Draft/final text must match both exact hashes.")
    hunks = [
        DiffSpan(initial_start=a, initial_end=b, final_start=c, final_end=d)
        for tag, a, b, c, d in SequenceMatcher(
            None, request.initial_text, request.final_text, autojunk=False
        ).get_opcodes()
        if tag != "equal"
    ]
    categories: set[DiffCategory] = set()
    for label in request.labels:
        if not request.classifier_reference or not (
            0 <= label.initial_start <= label.initial_end <= len(request.initial_text)
            and 0 <= label.final_start <= label.final_end <= len(request.final_text)
        ):
            reject("Category proposals require a classifier reference and valid exact offsets.")
        before = request.initial_text[label.initial_start : label.initial_end]
        after = request.final_text[label.final_start : label.final_end]
        if before == after or not any(
            overlaps(label.initial_start, label.initial_end, h.initial_start, h.initial_end)
            and overlaps(label.final_start, label.final_end, h.final_start, h.final_end)
            for h in hunks
        ):
            reject("Category evidence must actually intersect a changed span on both sides.")
        categories.add(label.category)
    status: str = "proposed" if categories else "needs_classification"
    if not hunks:
        status = "unchanged"
    elif not categories and (
        "".join(c for c in request.initial_text if c.isalnum())
        == "".join(c for c in request.final_text if c.isalnum())
    ):
        categories.add("style")
        status = "punctuation_only"
    return MessageDiffResult.model_validate(
        dict(
            event_id=request.event_id,
            changed=bool(hunks),
            categories=sorted(categories),
            hunks=hunks,
            classification_status=status,
            initial_hash=request.initial_hash,
            final_hash=request.final_hash,
        )
    )
