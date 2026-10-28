from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from jobagent.errors import ContractValidationError
from jobagent.storage.database import Database

NOW = datetime(2026, 10, 28, 2, tzinfo=UTC)


def repository(tmp_path: Path):
    from jobagent.storage.sourcing_repository import SqliteSourcingRepository

    database = Database(tmp_path / "budget.sqlite3")
    database.migrate()
    return SqliteSourcingRepository(database)


def start(repo, run_id="RUN_1", daily_cap=50, **changes):
    from jobagent.schemas.sourcing import SourcingRunRequest

    return repo.start_run(SourcingRunRequest(
        run_id=run_id, candidate_id="CAND_DEMO", source="boss", **changes,
    ), now=NOW, daily_cap=daily_cap)


def attempt(repo, number=1, run_id="RUN_1", **changes):
    from jobagent.schemas.sourcing import SourcingAttemptRequest

    values = {
        "attempt_id": f"ATT_{number}", "run_id": run_id, "kind": "detail",
        "source_job_id": "synthetic-1",
        "url": "https://www.zhipin.com/job_detail/synthetic-1.html",
    }
    values.update(changes)
    return repo.reserve(SourcingAttemptRequest.model_validate(values), now=NOW)


def finish(repo, number=1, **changes):
    from jobagent.schemas.sourcing import SourcingResultRequest

    values = {"attempt_id": f"ATT_{number}", "outcome": "failed"}
    values.update(changes)
    return repo.complete(SourcingResultRequest.model_validate(values), now=NOW)


def test_repeated_job_reads_and_failed_reads_each_consume_a_slot(tmp_path):
    repo = repository(tmp_path)
    start(repo, detail_limit=2)
    assert attempt(repo).allowed
    finish(repo)
    assert attempt(repo, 2).allowed
    denied = attempt(repo, 3)
    assert not denied.allowed and denied.reason == "round_detail_limit"
    budget = repo.budget("boss", daily_cap=50, now=NOW)
    assert budget.read_today == 2
    assert budget.remaining == 48


def test_attempt_replay_does_not_execute_twice_and_changed_id_content_is_rejected(tmp_path):
    repo = repository(tmp_path)
    start(repo)
    assert attempt(repo).allowed
    replay = attempt(repo)
    assert not replay.allowed and replay.reason == "already_reserved"
    assert repo.budget("boss", daily_cap=50, now=NOW).read_today == 1
    with pytest.raises(ContractValidationError):
        attempt(repo, source_job_id="another")


def test_run_budget_is_frozen_and_same_run_start_is_idempotent(tmp_path):
    repo = repository(tmp_path)
    run = start(repo, query_limit=1, detail_limit=2)
    assert start(repo, query_limit=1, detail_limit=2) == run
    with pytest.raises(ContractValidationError):
        start(repo, query_limit=6, detail_limit=50)


def test_query_budget_and_observed_listings_are_separate_from_detail_reads(tmp_path):
    repo = repository(tmp_path)
    start(repo, query_limit=1)
    query = {"kind": "query", "source_job_id": None, "url": None, "search_term": "合成产品"}
    assert attempt(repo, **query).allowed
    finish(repo, outcome="complete", listing_count=10)
    denied = attempt(repo, 2, **query)
    assert not denied.allowed and denied.reason == "round_query_limit"
    budget = repo.budget("boss", daily_cap=50, now=NOW)
    assert budget.query_attempts_today == 1
    assert budget.listing_observations_today == 10
    assert budget.read_today == 0


def test_daily_cap_is_shared_by_rounds_and_candidate_work_in_same_database(tmp_path):
    repo = repository(tmp_path)
    start(repo, daily_cap=1)
    start(repo, run_id="RUN_2", daily_cap=1)
    assert attempt(repo).allowed
    denied = attempt(repo, 2, run_id="RUN_2")
    assert not denied.allowed and denied.reason == "daily_detail_limit"


def test_concurrent_last_daily_slot_has_only_one_winner(tmp_path):
    repo = repository(tmp_path)
    start(repo, daily_cap=1)
    with ThreadPoolExecutor(max_workers=2) as workers:
        permits = list(workers.map(lambda n: attempt(repo, n), [1, 2]))
    assert sum(p.allowed for p in permits) == 1
    assert repo.budget("boss", daily_cap=1, now=NOW).remaining == 0


def test_gate_result_stops_new_query_and_detail_reservations_for_that_board_day(tmp_path):
    repo = repository(tmp_path)
    start(repo)
    attempt(repo)
    finish(repo, outcome="gate")
    assert attempt(repo, 2).reason == "site_halted"
    assert attempt(repo, 3, kind="query", source_job_id=None, url=None,
                   search_term="合成产品").reason == "site_halted"
    assert repo.budget("boss", daily_cap=50, now=NOW).halted


def test_local_midnight_expires_old_round_and_resets_daily_counts(tmp_path):
    from jobagent.schemas.sourcing import SourcingAttemptRequest, SourcingRunRequest

    repo = repository(tmp_path)
    before = datetime(2026, 10, 28, 15, 59, tzinfo=UTC)
    after = before + timedelta(minutes=2)
    request = SourcingRunRequest(run_id="RUN_1", candidate_id="CAND_DEMO", source="boss")
    repo.start_run(request, now=before, daily_cap=1)
    attempt_data = SourcingAttemptRequest(
        attempt_id="ATT_A", run_id="RUN_1", kind="detail", source_job_id="one",
        url="https://www.zhipin.com/job_detail/one.html",
    )
    assert repo.reserve(attempt_data, now=before).allowed
    assert repo.budget("boss", daily_cap=1, now=after).read_today == 0
    denied = repo.reserve(attempt_data.model_copy(update={"attempt_id": "ATT_B"}), now=after)
    assert not denied.allowed and denied.reason == "expired_run"


def test_result_replay_is_idempotent_but_cannot_rewrite_outcome(tmp_path):
    repo = repository(tmp_path)
    start(repo)
    attempt(repo)
    first = finish(repo)
    assert finish(repo) == first
    with pytest.raises(ContractValidationError):
        finish(repo, outcome="complete")


def test_legacy_observations_and_subsequent_reserved_reads_each_remain_counted(tmp_path):
    from jobagent.jobs.normalization import JobNormalizer
    from jobagent.schemas.job_intelligence import SourceJobRecord
    from jobagent.storage.job_repository import SqliteJobRepository

    repo = repository(tmp_path)
    jobs = SqliteJobRepository(repo.database)
    raw = SourceJobRecord(
        source="boss", source_job_id="synthetic-1", title="合成岗位", company="合成公司",
        location="上海", jd_raw="负责合成产品的需求与交付。仅用于测试。",
        url="https://www.zhipin.com/job_detail/synthetic-1.html", collected_at=NOW,
    )
    jobs.save_job(JobNormalizer().normalize(raw))
    budget = repo.budget("boss", daily_cap=50, now=NOW)
    assert budget.read_today == 1 and budget.legacy_unmetered == 1
    start(repo)
    attempt(repo)
    attempt(repo, 2)
    budget = repo.budget("boss", daily_cap=50, now=NOW)
    assert budget.read_today == 3 and budget.legacy_unmetered == 1


def test_invalid_detail_target_and_excessive_round_limits_are_rejected(tmp_path):
    from jobagent.schemas.sourcing import SourcingAttemptRequest, SourcingRunRequest

    with pytest.raises(ValueError):
        SourcingAttemptRequest(attempt_id="ATT", run_id="RUN", kind="detail")
    with pytest.raises(ValueError):
        SourcingRunRequest(run_id="RUN", candidate_id="CAND_DEMO", source="boss", query_limit=12)
    with pytest.raises(ValueError):
        SourcingRunRequest(run_id="RUN", candidate_id="CAND_DEMO", source="boss", detail_limit=51)


def test_unknown_attempt_and_wrong_result_shape_are_rejected(tmp_path):
    repo = repository(tmp_path)
    start(repo)
    with pytest.raises(ContractValidationError):
        finish(repo)
    attempt(repo)
    with pytest.raises(ContractValidationError):
        finish(repo, listing_count=10)


def test_earlier_unmetered_read_is_not_erased_by_a_later_reserved_read(tmp_path):
    from jobagent.jobs.normalization import JobNormalizer
    from jobagent.schemas.job_intelligence import SourceJobRecord
    from jobagent.storage.job_repository import SqliteJobRepository

    repo = repository(tmp_path)
    raw = SourceJobRecord(
        source="boss", source_job_id="synthetic-1", title="合成岗位", company="合成公司",
        location="上海", jd_raw="用于预算测试的合成岗位描述。此为虚构数据。",
        url="https://www.zhipin.com/job_detail/synthetic-1.html",
        collected_at=NOW-timedelta(minutes=1),
    )
    SqliteJobRepository(repo.database).save_job(JobNormalizer().normalize(raw))
    start(repo)
    attempt(repo)
    budget = repo.budget("boss", daily_cap=50, now=NOW)
    assert budget.read_today == 2 and budget.legacy_unmetered == 1


def test_import_after_reservation_does_not_charge_again_and_old_estimate_is_retained(tmp_path):
    from jobagent.jobs.normalization import JobNormalizer
    from jobagent.schemas.job_intelligence import SourceJobRecord
    from jobagent.storage.job_repository import SqliteJobRepository

    repo = repository(tmp_path)
    start(repo)
    attempt(repo)
    raw = SourceJobRecord(
        source="boss", source_job_id="synthetic-1", title="合成岗位", company="合成公司",
        location="上海", jd_raw="用于预算测试的合成岗位描述。此为虚构数据。",
        url="https://www.zhipin.com/job_detail/synthetic-1.html", collected_at=NOW,
    )
    jobs = SqliteJobRepository(repo.database)
    jobs.save_job(JobNormalizer().normalize(raw))
    assert repo.budget("boss", daily_cap=50, now=NOW).read_today == 1
    assert repo.budget("boss", daily_cap=50, now=NOW).legacy_unmetered == 0


def test_refreshing_a_legacy_job_cannot_refund_the_earlier_observed_read(tmp_path):
    from jobagent.jobs.normalization import JobNormalizer
    from jobagent.schemas.job_intelligence import SourceJobRecord
    from jobagent.storage.job_repository import SqliteJobRepository

    repo = repository(tmp_path)
    jobs = SqliteJobRepository(repo.database)
    raw = SourceJobRecord(
        source="boss", source_job_id="synthetic-1", title="合成岗位", company="合成公司",
        location="上海", jd_raw="用于预算测试的合成岗位描述。此为虚构数据。",
        url="https://www.zhipin.com/job_detail/synthetic-1.html",
        collected_at=NOW-timedelta(minutes=1),
    )
    jobs.save_job(JobNormalizer().normalize(raw))
    start(repo)
    attempt(repo)
    jobs.save_job(JobNormalizer().normalize(raw.model_copy(update={"collected_at": NOW})))
    assert repo.budget("boss", daily_cap=50, now=NOW).read_today == 2
