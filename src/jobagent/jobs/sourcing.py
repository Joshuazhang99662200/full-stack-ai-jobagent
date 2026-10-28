"""Pure decisions for a host's read-only search attempts."""
from datetime import datetime, timedelta, timezone

from jobagent.schemas.sourcing import (
    SourcingAttemptRequest,
    SourcingBudget,
    SourcingRefusal,
    SourcingRun,
)

# Current host-browser sources share China's calendar day. No host-local clock.
SOURCING_DAY = timezone(timedelta(hours=8), "Asia/Shanghai")


def refusal_reason(
    request: SourcingAttemptRequest,
    run: SourcingRun,
    budget: SourcingBudget,
    *,
    query_count: int,
    detail_count: int,
    now: datetime,
) -> SourcingRefusal | None:
    if run.opened_at.astimezone(SOURCING_DAY).date() != now.astimezone(SOURCING_DAY).date():
        return "expired_run"
    if budget.halted:
        return "site_halted"
    if request.kind == "query" and query_count >= run.query_limit:
        return "round_query_limit"
    if request.kind == "detail":
        if budget.remaining == 0:
            return "daily_detail_limit"
        if detail_count >= run.detail_limit:
            return "round_detail_limit"
    return None
