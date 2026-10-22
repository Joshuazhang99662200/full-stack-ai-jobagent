from datetime import UTC, datetime, timedelta, timezone

import pytest

from jobagent.patrol.schedule import decide
from jobagent.schemas.patrol import PatrolMode, PatrolSchedule

SHANGHAI = timezone(timedelta(hours=8))
SCHEDULE = PatrolSchedule()


def at(day: int, hour: int, minute: int = 0) -> datetime:
    """2026-10-18 is a Sunday; day 0..6 counts from it."""
    return datetime(2026, 10, 18 + day, hour, minute, tzinfo=SHANGHAI).astimezone(UTC)


@pytest.mark.parametrize(
    ("moment", "active"),
    [
        (at(0, 19, 59), False),  # Sunday before 20:00
        (at(0, 20, 0), True),  # Sunday evening window opens
        (at(0, 23, 59), True),
        (at(3, 3, 0), True),  # Wednesday small hours: Monday to Thursday run all day
        (at(5, 19, 59), True),  # Friday before 20:00
        (at(5, 20, 0), False),  # Friday evening closes the week
        (at(6, 12, 0), False),  # Saturday
    ],
)
def test_checks_only_run_inside_the_weekly_windows(moment: datetime, active: bool) -> None:
    assert decide(moment, SCHEDULE, last_check_at=None, last_inbound_at=None).active is active


def test_outside_the_windows_the_next_check_is_when_the_next_window_opens() -> None:
    decision = decide(at(6, 12), SCHEDULE, last_check_at=None, last_inbound_at=None)

    assert decision.mode is PatrolMode.OFF and not decision.due
    assert decision.next_check_at == at(7, 20)


def test_the_base_rhythm_is_one_check_an_hour() -> None:
    now = at(2, 10)

    assert decide(now, SCHEDULE, last_check_at=None, last_inbound_at=None).due
    recent = decide(now, SCHEDULE, last_check_at=now - timedelta(minutes=40), last_inbound_at=None)
    assert recent.mode is PatrolMode.BASE and not recent.due
    assert recent.next_check_at == now + timedelta(minutes=20)
    # Runs are woken a few minutes late; a check that is nearly an hour old is due.
    hour_old = now - timedelta(minutes=58)
    assert decide(now, SCHEDULE, last_check_at=hour_old, last_inbound_at=None).due


def test_a_reply_tightens_the_rhythm_to_fifteen_minutes_for_that_hour() -> None:
    now = at(2, 10)
    replied = now - timedelta(minutes=20)

    eight = now - timedelta(minutes=8)
    soon = decide(now, SCHEDULE, last_check_at=eight, last_inbound_at=replied)
    assert soon.mode is PatrolMode.ESCALATED and not soon.due
    fourteen = now - timedelta(minutes=14)
    assert decide(now, SCHEDULE, last_check_at=fourteen, last_inbound_at=replied).due

    later = decide(
        now, SCHEDULE, last_check_at=now - timedelta(minutes=14),
        last_inbound_at=now - timedelta(minutes=70),
    )
    assert later.mode is PatrolMode.BASE and not later.due


def test_every_check_fetches_new_postings_before_reading_messages() -> None:
    decision = decide(at(2, 10), SCHEDULE, last_check_at=None, last_inbound_at=None)

    assert decision.steps[0] == "fetch_new_postings"


def test_a_check_still_running_is_not_started_twice() -> None:
    now = at(2, 10)

    decision = decide(
        now, SCHEDULE, last_check_at=None, last_inbound_at=None,
        open_check=("PCHECK_A", now - timedelta(minutes=20)),
    )

    assert not decision.due and decision.in_progress_check_id == "PCHECK_A"


def test_a_check_cut_off_midway_is_resumed_at_the_next_wake() -> None:
    now = at(2, 10)

    decision = decide(
        now, SCHEDULE, last_check_at=now - timedelta(hours=2), last_inbound_at=None,
        open_check=("PCHECK_A", now - timedelta(minutes=50)),
    )

    assert decision.due and decision.abandoned_check_id == "PCHECK_A"
