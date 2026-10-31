import pytest

from jobagent.errors import ContractValidationError
from jobagent.schemas.sourcing import SourcingAttemptRequest, SourcingQueryCapture
from jobagent.storage.sourcing_repository import SqliteSourcingRepository
from tests.jobs.test_query_selection import listing
from tests.storage.test_configured_sourcing import NOW, configured, intent


def setup(tmp_path):
    from jobagent.storage.query_repository import SqliteQueryRepository

    db, rules = configured(tmp_path)
    sourcing = SqliteSourcingRepository(db)
    sourcing.start_run(intent(rules), now=NOW, daily_cap=9)
    for attempt in ["QUERY_ONE", "QUERY_TWO"]:
        sourcing.reserve(
            SourcingAttemptRequest(
                attempt_id=attempt,
                run_id="RUN_SYNTH",
                kind="query",
                search_term="synthetic query",
            ),
            now=NOW,
        )
    return db, SqliteQueryRepository(db)


def test_capture_is_atomic_replay_safe_and_deduplicates_across_queries(tmp_path):
    db, repo = setup(tmp_path)
    capture = SourcingQueryCapture(
        attempt_id="QUERY_ONE",
        items=[listing(1), listing(2)],
        loaded=True,
        access_state="public",
        next_cursor="synthetic-page-2",
    )
    first = repo.take(capture, now=NOW)
    assert first.requested == 3 and first.shortfall == 1
    assert first.next_cursor == "synthetic-page-2" and not first.traversal_complete
    assert repo.take(capture, now=NOW) == first
    second = repo.take(
        capture.model_copy(
            update={
                "attempt_id": "QUERY_TWO",
                "items": [listing(2), listing(3), listing(4), listing(5)],
            }
        ),
        now=NOW,
    )
    assert [item.source_job_id for item in second.items] == ["3", "4"]
    assert second.duplicate_ids == ["2"] and second.taken_count == 3
    with db.connect() as connection:
        assert connection.execute("SELECT count(*) FROM sourcing_results").fetchone()[0] == 2
    with pytest.raises(ContractValidationError, match=r"different|changed"):
        repo.take(capture.model_copy(update={"items": [listing(9)]}), now=NOW)


@pytest.mark.parametrize("field,value", [("loaded", False), ("access_state", "unknown")])
def test_unavailable_or_loading_capture_does_not_become_successful_zero(tmp_path, field, value):
    db, repo = setup(tmp_path)
    capture = SourcingQueryCapture.model_validate(
        {
            "attempt_id": "QUERY_ONE",
            "items": [],
            "loaded": True,
            "access_state": "public",
            field: value,
        }
    )
    with pytest.raises(ContractValidationError, match=r"loaded|accessible"):
        repo.take(capture, now=NOW)
    with db.connect() as connection:
        assert connection.execute("SELECT count(*) FROM sourcing_results").fetchone()[0] == 0


def test_only_one_real_query_claim_can_be_issued_and_replay_requires_readback(tmp_path):
    _, repo = setup(tmp_path)
    assert (
        repo.claim(
            "QUERY_ONE",
            run_id="RUN_SYNTH",
            source="boss",
            query="synthetic query",
            request_digest="sha256:" + "a" * 64,
            now=NOW,
        )
        is None
    )
    with pytest.raises(ContractValidationError, match=r"unknown|claimed|verification"):
        repo.claim(
            "QUERY_ONE",
            run_id="RUN_SYNTH",
            source="boss",
            query="synthetic query",
            request_digest="sha256:" + "a" * 64,
            now=NOW,
        )


def test_configured_success_cannot_bypass_the_result_capture_boundary(tmp_path):
    from jobagent.schemas.sourcing import SourcingResultRequest

    db, _ = setup(tmp_path)
    with pytest.raises(ContractValidationError, match=r"capture|selection"):
        SqliteSourcingRepository(db).complete(
            SourcingResultRequest(attempt_id="QUERY_ONE", outcome="complete", listing_count=2),
            now=NOW,
        )


def test_claim_rechecks_round_budget_before_any_real_query(tmp_path):
    db, repo = setup(tmp_path)
    sourcing = SqliteSourcingRepository(db)
    for number in range(2):
        sourcing.reserve(
            SourcingAttemptRequest(
                attempt_id=f"DETAIL_{number}",
                run_id="RUN_SYNTH",
                kind="detail",
                source_job_id=str(number),
                url=f"https://www.zhipin.com/job_detail/{number}.html",
            ),
            now=NOW,
        )
    with pytest.raises(ContractValidationError, match="budget"):
        repo.claim(
            "QUERY_ONE",
            run_id="RUN_SYNTH",
            source="boss",
            query="synthetic query",
            request_digest="sha256:" + "a" * 64,
            now=NOW,
        )
    with db.connect() as connection:
        assert connection.execute("SELECT count(*) FROM sourcing_query_claims").fetchone()[0] == 0
