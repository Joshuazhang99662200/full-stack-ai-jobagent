from datetime import UTC, datetime, timedelta

import pytest

from jobagent.errors import ContractValidationError, StorageError
from jobagent.schemas.sourcing import (
    ReadOutcome,
    ReadReservation,
    SourcingAttemptRequest,
    SourcingResultRequest,
    SourcingRunRequest,
)
from jobagent.storage.database import Database
from jobagent.storage.read_repository import SqliteReadRepository
from jobagent.storage.sourcing_repository import SqliteSourcingRepository

NOW = datetime(2026, 10, 30, 9, tzinfo=UTC)


def ledgers(tmp_path):
    db = Database(tmp_path / "merged.sqlite3")
    db.migrate()
    rounds, reads = SqliteSourcingRepository(db), SqliteReadRepository(db)
    rounds.start_run(
        SourcingRunRequest(run_id="RUN_SYNTH", candidate_id="CAND_SYNTH", source="boss"),
        now=NOW, daily_cap=2,
    )
    return db, rounds, reads


def detail(attempt_id):
    return SourcingAttemptRequest(
        attempt_id=attempt_id, run_id="RUN_SYNTH", kind="detail",
        source_job_id="SYNTH_JOB", url="https://www.zhipin.com/job_detail/synthetic.html",
    )


def read(attempt_id):
    return ReadReservation(
        attempt_id=attempt_id, source="boss", profile="standard", expected_daily_cap=2,
        target_url="https://www.zhipin.com/job_detail/synthetic.html",
    )


def test_both_entry_points_share_the_daily_cap(tmp_path):
    _, rounds, reads = ledgers(tmp_path)
    assert rounds.reserve(detail("ROUND_1"), now=NOW).allowed
    assert reads.reserve(read("READ_1"), daily_cap=2, now=NOW).allowed
    with pytest.raises(ContractValidationError, match="budget"):
        reads.reserve(read("READ_2"), daily_cap=2, now=NOW)
    permit = rounds.reserve(detail("ROUND_2"), now=NOW)
    assert not permit.allowed and permit.reason == "daily_detail_limit"
    assert rounds.budget("boss", daily_cap=2, now=NOW).read_today == 2


def test_read_gate_stops_round_entry(tmp_path):
    _, rounds, reads = ledgers(tmp_path)
    reads.reserve(read("READ_GATE"), daily_cap=2, now=NOW)
    reads.record(ReadOutcome(attempt_id="READ_GATE", status="risk_control"), now=NOW)
    permit = rounds.reserve(detail("ROUND_NEW"), now=NOW)
    assert not permit.allowed and permit.reason == "site_halted"


def test_round_read_receipt_binds_to_the_raw_observation(tmp_path):
    from jobagent.jobs.normalization import JobNormalizer
    from jobagent.storage.job_repository import SqliteJobRepository
    from tests.storage.test_observation_history import record

    db, rounds, _ = ledgers(tmp_path)
    attempt = detail("ROUND_CAPTURE")
    rounds.reserve(attempt, now=NOW)
    rounds.complete(SourcingResultRequest(attempt_id=attempt.attempt_id, outcome="complete"),
                    now=NOW + timedelta(seconds=1))
    captured = record(
        source="boss", source_job_id=attempt.source_job_id, url=attempt.url,
        read_attempt_id=attempt.attempt_id, collected_at=NOW + timedelta(seconds=1),
    )
    repository = SqliteJobRepository(db)
    repository.save_observation(captured, JobNormalizer().normalize(captured))
    assert len(repository.observations(JobNormalizer().normalize(captured).id)) == 1


def test_attempt_id_cannot_be_reused_between_the_two_entry_points(tmp_path):
    _, rounds, reads = ledgers(tmp_path)
    assert rounds.reserve(detail("SHARED_ID"), now=NOW).allowed
    with pytest.raises(ContractValidationError, match="another"):
        reads.reserve(read("SHARED_ID"), daily_cap=2, now=NOW)


def test_round_gate_stops_read_entry_on_reservation_and_observation_days(tmp_path):
    _, rounds, reads = ledgers(tmp_path)
    rounds.reserve(detail("ROUND_GATE"), now=NOW)
    tomorrow = NOW + timedelta(days=1)
    rounds.complete(SourcingResultRequest(attempt_id="ROUND_GATE", outcome="gate"), now=tomorrow)
    for clock in [NOW, tomorrow]:
        with pytest.raises(ContractValidationError, match="stopped"):
            reads.reserve(read("READ_NEW"), daily_cap=2, now=clock)


def test_published_schema_26_upgrades_without_losing_existing_facts(tmp_path):
    from importlib import resources

    from jobagent.storage.database import _MIGRATION_FILES

    db = Database(tmp_path / "published.sqlite3")
    with db.connect() as connection:
        for number in range(1, 27):
            connection.executescript(resources.files("jobagent.storage.migrations").joinpath(
                _MIGRATION_FILES[number],
            ).read_text(encoding="utf-8"))
        connection.execute("INSERT INTO sourcing_runs VALUES (?, ?, ?)",
                           ("SYNTH_OLD", "boss", "{}"))
        connection.commit()
    db.migrate()
    with db.connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 30
        assert connection.execute("SELECT count(*) FROM sourcing_runs").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM dynamic_rule_versions").fetchone()[0] == 0


def test_unpublished_conflicting_schema_is_rejected_before_any_migration(tmp_path):
    db = Database(tmp_path / "unpublished.sqlite3")
    with db.connect() as connection:
        connection.executescript(
            "CREATE TABLE worker_fetch_receipts(task_id TEXT); PRAGMA user_version = 17;",
        )
    with pytest.raises(StorageError, match="unpublished local schema"):
        db.migrate()
    with db.connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 17
        assert connection.execute("SELECT count(*) FROM sqlite_master WHERE type='table'")
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name='job_intake_entries'",
        ).fetchone() is None
