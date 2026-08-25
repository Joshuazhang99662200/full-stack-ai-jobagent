"""Bounded text extraction shared by public-page job connectors.

Every job board renders the JD next to material that must never reach `jd_raw`:
company blurbs, anti-fraud notices, "recommended jobs" rails. Splicing those in
would silently corrupt requirement extraction, so extraction is bounded at both
ends and fails loudly rather than returning a partial or padded body.

Connectors supply only their own headings and gate markers; the cutting,
gate detection and length checks live here once.
"""

import html
import re
from dataclasses import dataclass, field

from jobagent.errors import InvalidProviderOutputError, UserInterventionRequiredError

# Text that means the page withheld the JD behind login, verification or rate
# limiting. These are platform states for a human to clear, never retry targets.
DEFAULT_GATE_MARKERS: tuple[str, ...] = (
    "登录查看",
    "请登录",
    "登录后查看",
    "安全验证",
    "验证码",
    "访问过于频繁",
    "人机验证",
    "滑动验证",
)

MIN_JD_LENGTH = 30


def strip_markup(fragment: str) -> str:
    """Reduce HTML to visible lines, preserving block boundaries."""
    without_scripts = re.sub(r"<(script|style)\b.*?</\1>", " ", fragment, flags=re.S | re.I)
    with_breaks = re.sub(r"<(br|/p|/div|/li|/h\d)\s*/?>", "\n", without_scripts, flags=re.I)
    text = re.sub(r"<[^>]+>", "", with_breaks)
    text = html.unescape(text)
    lines = [" ".join(line.split()) for line in text.split("\n")]
    return "\n".join(line for line in lines if line and not line.startswith("-->"))


@dataclass(frozen=True)
class ExtractionRules:
    """Where one platform's JD starts and stops."""

    source: str
    # Tried in order; the first heading present wins.
    start_headings: tuple[str, ...]
    # The JD ends at whichever of these appears first after the start.
    stop_headings: tuple[str, ...] = ()
    gate_markers: tuple[str, ...] = field(default=DEFAULT_GATE_MARKERS)
    min_length: int = MIN_JD_LENGTH


def extract_bounded(page: str, rules: ExtractionRules, *, job_id: str) -> str:
    """Cut the JD out of a rendered page, or fail with a typed error.

    Raises `UserInterventionRequiredError` when the page shows a gate, and
    `InvalidProviderOutputError` when the body is absent or too short to trust.
    """
    text = strip_markup(page)

    start = -1
    heading_length = 0
    for heading in rules.start_headings:
        found = text.find(heading)
        if found >= 0:
            start = found
            heading_length = len(heading)
            break

    if start < 0:
        _raise_for_gate(text, rules, job_id)
        raise InvalidProviderOutputError(
            "The detail page contained no job description section.",
            details={"source": rules.source, "job_id": job_id},
        )

    body = text[start + heading_length :]
    cuts = [index for index in (body.find(stop) for stop in rules.stop_headings) if index > 0]
    if cuts:
        body = body[: min(cuts)]

    jd_raw = body.strip()
    if len(jd_raw) < rules.min_length:
        # A stub body usually means the page rendered a gate in place of the JD.
        _raise_for_gate(text, rules, job_id)
        raise InvalidProviderOutputError(
            "The extracted job description was too short to trust.",
            details={"source": rules.source, "job_id": job_id, "length": len(jd_raw)},
        )
    return jd_raw


def _raise_for_gate(text: str, rules: ExtractionRules, job_id: str) -> None:
    hit = next((marker for marker in rules.gate_markers if marker in text), None)
    if hit is None:
        return
    raise UserInterventionRequiredError(
        "The platform withheld the job description behind a gate.",
        details={
            "source": rules.source,
            "job_id": job_id,
            "gate_marker": hit,
            "hint": "Open the posting in your own browser and supply the JD text.",
        },
    )
