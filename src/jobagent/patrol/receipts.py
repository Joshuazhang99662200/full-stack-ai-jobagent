# ruff: noqa: RUF001  -- board text carries full-width brackets and punctuation by design.
"""Read receipts from a board's message list, matched to stored conversations.

A board prefixes our latest message with a status word ("[送达]", "[已读]"). Which
words mean what is declared in the board's manifest, never guessed. A row is
matched to a conversation only when exactly one fits; anything else is reported
so a person can place it, rather than attributed to the nearest guess.
"""

import re
import unicodedata
from collections.abc import Sequence

from jobagent.schemas.conversation import Conversation
from jobagent.schemas.patrol import (
    ConversationReceipt,
    PatrolSnapshot,
    ReceiptReport,
    ReceiptStatus,
    SnapshotItem,
    UnmatchedReceipt,
)
from jobagent.schemas.sources import ObservabilitySpec

# Message lists append the recruiter's role to the company line ("某公司HR").
_ROLE_SUFFIXES = tuple(
    sorted(("招聘专家", "招聘助理", "招聘者", "招聘", "人事", "hr"), key=len, reverse=True)
)
# What a legal name adds to a brand ("某某" -> "某某信息技术有限公司").
_LEGAL_TAILS = tuple(
    sorted(
        (
            "股份有限公司",
            "有限责任公司",
            "有限公司",
            "信息技术",
            "网络科技",
            "科技",
            "技术",
            "网络",
        ),
        key=len,
        reverse=True,
    )
)
_TITLE_MIN = 4  # a shorter cut title could begin anything
_BRAND_MIN = 4  # a shorter stem is too common to stand for one company
_OPEN, _CLOSE = "(（", ")）"
_ROLE_DOT = "·"
_HEADHUNTER = re.compile(r"猎头[:：]([^,，;；、()（）]+)")
_NOTE_BREAKS = ",，;；、"


def receipt_status(item: SnapshotItem, spec: ObservabilitySpec | None) -> ReceiptStatus | None:
    """What the board shows about our last message in this row, if anything."""
    if item.last_from != "us":
        return None
    if spec is None:
        return None
    if item.our_status == "read":
        return "read" if spec.read_markers else None
    if item.our_status == "delivered":
        return "delivered"
    preview = item.preview.lstrip()
    if any(preview.startswith(marker) for marker in spec.read_markers):
        return "read"
    if any(preview.startswith(marker) for marker in spec.delivered_markers):
        return "delivered"
    return None


def _outside_and_groups(text: str) -> tuple[str, list[str]]:
    """Text outside every top-level bracket pair, and the text inside each pair."""
    outside: list[str] = []
    groups: list[str] = []
    depth = 0
    for char in text:
        if char in _OPEN:
            if depth == 0:
                groups.append("")
            else:
                groups[-1] += char
            depth += 1
        elif char in _CLOSE and depth > 0:
            depth -= 1
            if depth > 0:
                groups[-1] += char
        elif depth > 0:
            groups[-1] += char
        elif char not in _CLOSE:
            outside.append(char)
    return "".join(outside), groups


def _core(company: str) -> str:
    """The company name alone: notes in brackets and the word 猎头 are not part of it.

    "猎头(某公司(上海)分公司,客户 X)" has nothing outside its brackets, so the first
    bracketed name is the company, cut at the first comma where notes begin.
    """
    text = "".join(company.split()).casefold().replace("猎头顾问", "").replace("猎头", "")
    outside, groups = _outside_and_groups(text)
    if outside or not groups:
        return outside
    first = groups[0]
    cut = min((first.index(c) for c in _NOTE_BREAKS if c in first), default=len(first))
    return _core(first[:cut])


def _without_role(key: str) -> str:
    for suffix in _ROLE_SUFFIXES:
        if key.endswith(suffix) and len(key) > len(suffix):
            return key[: -len(suffix)]
    return key


def _stem(key: str) -> str:
    """The key without the legal tails of a company name; the key itself if nothing is left."""
    while True:
        for tail in _LEGAL_TAILS:
            if key.endswith(tail) and len(key) > len(tail):
                key = key[: -len(tail)]
                break
        else:
            return key


def _headhunters(company: str) -> set[str]:
    """Names given as "猎头:某某" in a note: the agency standing in for an unnamed client."""
    return {_without_role(_core(name)) for name in _HEADHUNTER.findall("".join(company.split()))}


class _Name:
    """One company line read three ways, from the exact name to the loosest."""

    def __init__(self, company: str) -> None:
        core = _core(company)
        self.exact = _without_role(core)
        # "猎头顾问·某公司": the role stands before the dot.
        after_dot = _without_role(core.rsplit(_ROLE_DOT, 1)[-1]) if _ROLE_DOT in core else ""
        self.dot = {self.exact, after_dot, *_headhunters(company)} - {""}
        self.stems = {_stem(key) for key in self.dot}

    def loose_match(self, other: "_Name") -> bool:
        """The same company written as a brand on one side and a legal name on the other."""
        for stem in self.stems & other.stems:
            if len(stem) >= _BRAND_MIN and (stem in self.dot or stem in other.dot):
                return True
        return False


def _title(title: str) -> str:
    return "".join(unicodedata.normalize("NFKC", title).split()).casefold()


def _is_cut(title: str) -> bool:
    """A board shortens long titles: a bracket left open or a trailing ellipsis shows it."""
    opened = sum(title.count(c) for c in "(（")
    closed = sum(title.count(c) for c in ")）")
    return opened > closed or title.endswith(("…", "..."))


def _starts(cut: str, whole: str) -> bool:
    stem = cut.removesuffix("...").removesuffix("…")
    return _is_cut(cut) and len(stem) >= _TITLE_MIN and whole.startswith(stem)


def _by_title(candidates: list[Conversation], title: str) -> list[Conversation]:
    """The candidates this title fits: equal titles first, else a visibly cut one."""
    wanted = _title(title)
    equal = [c for c in candidates if _title(c.title) == wanted]
    if equal:
        return equal
    return [
        c
        for c in candidates
        if _starts(wanted, _title(c.title)) or _starts(_title(c.title), wanted)
    ]


def match_conversation(
    item: SnapshotItem, platform: str, conversations: Sequence[Conversation]
) -> tuple[str | None, str | None]:
    """The one conversation this row belongs to, or why there is none.

    The company is compared from the exact name outward: first as written (minus
    notes and a trailing role), then without a role before a middle dot, then as a
    brand against its legal name. The first step that finds anyone decides, and
    looser steps never choose between different companies. Several conversations
    with one company are told apart by title; if that does not leave exactly one,
    the row is ambiguous.
    """
    row = _Name(item.company)
    if not row.exact:
        return None, "no_match"
    named = [(c, _Name(c.company)) for c in conversations if c.platform == platform]
    tiers = (
        [c for c, name in named if name.exact == row.exact],
        [c for c, name in named if name.dot & row.dot],
        [c for c, name in named if row.loose_match(name)],
    )
    for level, found in enumerate(tiers):
        if not found:
            continue
        if level > 0 and len({_Name(c.company).exact for c in found}) > 1:
            return None, "ambiguous"
        if len(found) == 1:
            return found[0].conversation_id, None
        narrowed = _by_title(found, item.title) if item.title else found
        if len(narrowed) == 1:
            return narrowed[0].conversation_id, None
        return None, "ambiguous"
    return None, "no_match"


def receipts_from_snapshot(
    snapshot: PatrolSnapshot,
    conversations: Sequence[Conversation],
    spec: ObservabilitySpec | None,
) -> ReceiptReport:
    report = ReceiptReport()
    for item in snapshot.items:
        status = receipt_status(item, spec)
        if status is None:
            continue
        conversation_id, reason = match_conversation(item, snapshot.platform, conversations)
        if conversation_id is None:
            report.unmatched.append(
                UnmatchedReceipt(
                    key=item.key,
                    status=status,
                    reason="ambiguous" if reason == "ambiguous" else "no_match",
                )
            )
            continue
        report.receipts.append(
            ConversationReceipt(
                conversation_id=conversation_id,
                status=status,
                observed_at=snapshot.captured_at,
                snapshot_id=snapshot.snapshot_id,
            )
        )
    return report
