"""Decide whether a patrol check is due, from the schedule and what was recorded."""

from datetime import UTC, datetime, timedelta

from jobagent.outreach.service import PLATFORM_DAY
from jobagent.schemas.patrol import PatrolDecision, PatrolMode, PatrolSchedule, PatrolWindow

_SEARCH_DAYS = 8


def _bounds(window: PatrolWindow, day: datetime) -> tuple[datetime, datetime]:
    start = datetime.combine(day.date(), window.start, tzinfo=PLATFORM_DAY)
    end = (
        datetime.combine(day.date(), window.end, tzinfo=PLATFORM_DAY)
        if window.end is not None
        else datetime.combine(day.date() + timedelta(days=1), datetime.min.time(), PLATFORM_DAY)
    )
    return start, end


def _is_active(moment: datetime, schedule: PatrolSchedule) -> bool:
    local = moment.astimezone(PLATFORM_DAY)
    for window in schedule.windows:
        if window.weekday != local.weekday():
            continue
        start, end = _bounds(window, local)
        if start <= local < end:
            return True
    return False


def _next_opening(moment: datetime, schedule: PatrolSchedule) -> datetime:
    local = moment.astimezone(PLATFORM_DAY)
    openings = []
    for offset in range(_SEARCH_DAYS):
        day = local + timedelta(days=offset)
        for window in schedule.windows:
            if window.weekday == day.weekday():
                start, _ = _bounds(window, day)
                if start > local:
                    openings.append(start)
    return min(openings).astimezone(UTC)


def decide(
    now: datetime,
    schedule: PatrolSchedule,
    *,
    last_check_at: datetime | None,
    last_inbound_at: datetime | None,
    open_check: tuple[str, datetime] | None = None,
) -> PatrolDecision:
    """Is a check due now, at which rhythm, and when is the next one.

    `last_check_at` is the start of the latest finished check. `open_check` is a
    check that started and has not finished: recent, it is still running and no
    second one starts; stale, it was cut off and the next check is due at once.
    """
    if not _is_active(now, schedule):
        return PatrolDecision(
            active=False,
            mode=PatrolMode.OFF,
            due=False,
            last_check_at=last_check_at,
            last_inbound_at=last_inbound_at,
            next_check_at=_next_opening(now, schedule),
        )
    escalated = last_inbound_at is not None and now - last_inbound_at < timedelta(
        minutes=schedule.escalation_minutes
    )
    interval = (
        schedule.escalated_interval_minutes if escalated else schedule.base_interval_minutes
    )
    abandoned: str | None = None
    if open_check is not None:
        check_id, started = open_check
        if now - started < timedelta(minutes=schedule.stale_minutes):
            return PatrolDecision(
                active=True,
                mode=PatrolMode.ESCALATED if escalated else PatrolMode.BASE,
                due=False,
                interval_minutes=interval,
                last_check_at=last_check_at,
                last_inbound_at=last_inbound_at,
                next_check_at=started + timedelta(minutes=schedule.stale_minutes),
                in_progress_check_id=check_id,
            )
        abandoned = check_id
    if abandoned is not None or last_check_at is None:
        due, next_check = True, now
    else:
        next_check = last_check_at + timedelta(minutes=interval)
        due = now >= next_check - timedelta(minutes=schedule.slack_minutes)
    return PatrolDecision(
        active=True,
        mode=PatrolMode.ESCALATED if escalated else PatrolMode.BASE,
        due=due,
        interval_minutes=interval,
        last_check_at=last_check_at,
        last_inbound_at=last_inbound_at,
        next_check_at=now if due else next_check,
        abandoned_check_id=abandoned,
    )
