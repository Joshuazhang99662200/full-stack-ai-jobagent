"""Pure public-board policy units and conservative geography; no IO dependencies."""

import re
from typing import Literal

from jobagent.schemas.job_intelligence import CandidateFilterContext

BUDGET_NAMES = (
    "PUBLIC_CAREERS_HTTP_PER_DAY",
    "PUBLIC_CAREERS_HTTP_PER_ROUND",
    "PUBLIC_CAREERS_HTTP_PER_BOARD",
    "PUBLIC_CAREERS_QUERY_PER_ROUND",
    "PUBLIC_CAREERS_MAX_BYTES",
    "PUBLIC_CAREERS_TIMEOUT_SECONDS",
    "TOP_PER_QUERY",
)


def region_decision(
    location: str | None, context: CandidateFilterContext
) -> Literal["pass", "review", "reject"]:
    value = (location or "").strip().casefold()
    if (
        not context.allowed_locations
        or not value
        or value in {"unknown", "remote", "hybrid", "distributed", "worldwide"}
    ):
        return "review"
    if any(
        re.search(r"(?<!\w)" + re.escape(item.casefold()) + r"(?!\w)", value)
        for item in context.allowed_locations
    ):
        return "pass"
    if any(word in value for word in ("remote", "hybrid", "distributed")):
        return "review"
    if any(
        bool(re.search(r"[\u4e00-\u9fff]", item)) != bool(re.search(r"[\u4e00-\u9fff]", value))
        for item in context.allowed_locations
    ):
        return "review"
    return "reject"
