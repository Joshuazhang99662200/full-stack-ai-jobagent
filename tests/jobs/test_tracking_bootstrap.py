# ruff: noqa: RUF001 -- Synthetic Chinese evidence punctuation.
from datetime import timedelta

import pytest

from jobagent.errors import ContractValidationError
from tests.jobs.test_sent_tracking import NOW, event, proof


def test_late_registration_requires_actual_next_poll_and_does_not_backfill_checks():
    from jobagent.jobs.sent_tracking import start_tracking

    registered = NOW + timedelta(days=2)
    with pytest.raises(ContractValidationError):
        start_tracking(proof(), candidate_id="CAND_DEMO", tracking_id="TRACK_LATE", now=registered)
    next_poll = registered + timedelta(hours=4)
    history = start_tracking(
        proof(),
        candidate_id="CAND_DEMO",
        tracking_id="TRACK_LATE",
        now=registered,
        next_poll_at=next_poll,
    )
    value = history[-1].state
    assert value.check_count == 0 and value.last_checked_at is None
    assert value.missed_check_days == [] and value.registered_at == registered
    assert value.next_check_at == next_poll
    assert all(e.occurred_at == registered for e in history)


def test_late_bootstrap_first_real_check_expires_without_backfilled_counts():
    from jobagent.jobs.sent_tracking import advance, start_tracking

    registered = NOW + timedelta(days=2)
    next_poll = registered + timedelta(hours=4)
    state = start_tracking(
        proof(),
        candidate_id="CAND_DEMO",
        tracking_id="TRACK_LATE",
        now=registered,
        next_poll_at=next_poll,
    )[-1].state
    early = event(state, "no_reply", observed_at=registered)
    with pytest.raises(ContractValidationError):
        advance(state, early, now=registered)
    observed = event(state, "no_reply", observed_at=next_poll)
    state = advance(state, observed, now=next_poll)[-1].state
    assert state.check_count == 1 and state.next_check_at is None
    assert state.tracking_state.value == "closed" and state.abandon_reason == "no_reply_2d"
    with pytest.raises(ContractValidationError):
        advance(
            state,
            event(state, "no_reply", observed_at=next_poll, observation_id="ANOTHER_READ"),
            now=next_poll,
        )


def test_explicit_resume_cannot_pull_bootstrap_check_before_next_poll():
    from jobagent.jobs.sent_tracking import advance, start_tracking

    registered = NOW + timedelta(days=2)
    next_poll = registered + timedelta(hours=4)
    state = start_tracking(
        proof(),
        candidate_id="CAND_DEMO",
        tracking_id="TRACK_LATE",
        now=registered,
        next_poll_at=next_poll,
    )[-1].state
    anomaly = event(state, "anomaly", observed_at=registered, evidence_kind="platform_state")
    state = advance(state, anomaly, now=registered)[-1].state
    resume = event(
        state,
        "resume",
        observed_at=registered,
        evidence_kind="owner_message",
        owner_text="问题已处理，继续检查",
    )
    state = advance(state, resume, now=registered)[-1].state
    assert state.next_check_at == next_poll and state.check_count == 0


def test_bootstrap_repository_replay_is_frozen_and_due_starts_next_poll(tmp_path):
    from jobagent.storage.database import Database
    from jobagent.storage.sent_tracking_repository import SqliteSentTrackingRepository

    db = Database(tmp_path / "private.sqlite3")
    db.migrate()
    repo = SqliteSentTrackingRepository(db)
    registered = NOW + timedelta(days=2)
    next_poll = registered + timedelta(hours=4)
    row = repo.start(
        proof(),
        candidate_id="CAND_DEMO",
        tracking_id="TRACK_LATE",
        now=registered,
        next_poll_at=next_poll,
    )
    assert repo.due("CAND_DEMO", now=registered) == []
    assert repo.due("CAND_DEMO", now=next_poll) == [row]
    assert (
        repo.start(
            proof(),
            candidate_id="CAND_DEMO",
            tracking_id="TRACK_LATE",
            now=registered,
            next_poll_at=next_poll,
        )
        == row
    )
    with pytest.raises(ContractValidationError):
        repo.start(
            proof(),
            candidate_id="CAND_DEMO",
            tracking_id="TRACK_LATE",
            now=registered,
            next_poll_at=next_poll + timedelta(hours=1),
        )
