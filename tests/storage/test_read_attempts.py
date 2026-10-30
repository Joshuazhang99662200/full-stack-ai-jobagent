from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from pydantic import HttpUrl

from jobagent.errors import ContractValidationError
from jobagent.storage.database import Database


def setup(tmp_path):
    from jobagent.schemas.sourcing import ReadReservation
    from jobagent.storage.sourcing_repository import SqliteSourcingRepository

    db = Database(tmp_path / "reads.sqlite3")
    db.migrate()
    repo = SqliteSourcingRepository(db)
    request = ReadReservation(
        attempt_id="SYN_1", source="zhaopin", target_url="https://www.zhaopin.com/jobs/",
        profile="standard", expected_daily_cap=2,
    )
    return repo, request


def test_reservation_is_idempotent_and_failed_reads_still_consume(tmp_path):
    from jobagent.schemas.sourcing import ReadOutcome

    repo, request = setup(tmp_path)
    now = datetime.now(UTC)
    first = repo.reserve(request, daily_cap=2, now=now)
    replay = repo.reserve(request, daily_cap=2, now=now)
    assert first.request_digest == replay.request_digest
    assert first.allowed and not replay.allowed
    repo.record(ReadOutcome(attempt_id="SYN_1", status="failed"), now=now)
    assert repo.used("zhaopin", now=now) == 1
    repo.reserve(request.model_copy(update={"attempt_id": "SYN_2"}), daily_cap=2, now=now)
    with pytest.raises(ContractValidationError, match="budget"):
        repo.reserve(request.model_copy(update={"attempt_id": "SYN_3"}), daily_cap=2, now=now)


def test_conflicting_profile_or_same_id_changed_target_fails(tmp_path):
    repo, request = setup(tmp_path)
    now = datetime.now(UTC)
    with pytest.raises(ContractValidationError, match=r"profile|cap"):
        repo.reserve(request.model_copy(update={"profile": "expanded"}), daily_cap=2, now=now)
    repo.reserve(request, daily_cap=2, now=now)
    with pytest.raises(ContractValidationError, match="different"):
        repo.reserve(request.model_copy(update={"target_url": HttpUrl("https://example.test/other")}),
                     daily_cap=2, now=now)


def test_concurrent_reservations_never_exceed_cap(tmp_path):
    repo, request = setup(tmp_path)
    now = datetime.now(UTC)

    def reserve(index):
        try:
            repo.reserve(request.model_copy(update={"attempt_id": f"SYN_{index}"}),
                         daily_cap=2, now=now)
            return True
        except ContractValidationError:
            return False

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(reserve, range(8))) == 2
    assert repo.used("zhaopin", now=now) == 2


def test_login_or_unknown_read_stops_site_and_cannot_be_overwritten(tmp_path):
    from jobagent.schemas.sourcing import ReadOutcome

    repo, request = setup(tmp_path)
    now = datetime.now(UTC)
    repo.reserve(request, daily_cap=2, now=now)
    outcome = ReadOutcome(attempt_id="SYN_1", status="login_required")
    repo.record(outcome, now=now)
    repo.record(outcome, now=now)
    with pytest.raises(ContractValidationError, match="stopped"):
        repo.reserve(request.model_copy(update={"attempt_id": "SYN_NEW"}), daily_cap=2, now=now)
    with pytest.raises(ContractValidationError, match="different"):
        repo.record(ReadOutcome(attempt_id="SYN_1", status="read"), now=now)


def test_old_reservation_cannot_reauthorize_after_halt(tmp_path):
    from jobagent.schemas.sourcing import ReadOutcome

    repo, request = setup(tmp_path)
    now = datetime.now(UTC)
    repo.reserve(request, daily_cap=2, now=now)
    repo.record(ReadOutcome(attempt_id="SYN_1", status="risk_control"), now=now)
    assert not repo.reserve(request, daily_cap=2, now=now).allowed


def test_intervention_observed_after_midnight_also_halts_current_day(tmp_path):
    from datetime import timedelta

    from jobagent.schemas.sourcing import ReadOutcome

    repo, request = setup(tmp_path)
    before = datetime(2026, 10, 1, 15, 59, tzinfo=UTC)
    after = before + timedelta(minutes=2)
    repo.reserve(request, daily_cap=2, now=before)
    repo.record(ReadOutcome(attempt_id="SYN_1", status="risk_control"), now=after)
    with pytest.raises(ContractValidationError, match="stopped"):
        repo.reserve(request.model_copy(update={"attempt_id": "NEXT_DAY"}), daily_cap=2, now=after)


def test_negative_legacy_count_cannot_expand_budget(tmp_path):
    repo, request = setup(tmp_path)
    with pytest.raises(ContractValidationError, match="legacy"):
        repo.reserve(request, daily_cap=2, now=datetime.now(UTC), legacy_reads=-1)
