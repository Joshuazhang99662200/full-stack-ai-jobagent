from datetime import UTC, datetime

import pytest

from jobagent.errors import ContractValidationError

NOW = datetime(2026, 10, 28, 9, tzinfo=UTC)


def expanded(run_id="RUN_ONE", **changes):
    from jobagent.schemas.sourcing import SourcingRunRequest

    values = dict(
        run_id=run_id,
        candidate_id="CAND_DEMO",
        source="boss",
        budget_profile="muse-expanded-v1",
        query_limit=12,
        detail_limit=60,
        daily_detail_cap=240,
    )
    values.update(changes)
    return SourcingRunRequest.model_validate(values)


def test_expanded_is_explicit_complete_and_does_not_change_old_defaults():
    from jobagent.schemas.sourcing import SourcingRunRequest

    normal = SourcingRunRequest(run_id="RUN_ONE", candidate_id="CAND_DEMO", source="boss")
    assert normal.query_limit == 3 and normal.detail_limit == 20
    assert expanded().daily_detail_cap == 240
    for bad in [
        dict(budget_profile="conservative", query_limit=12),
        dict(budget_profile="conservative", detail_limit=60),
        dict(daily_detail_cap=241),
        dict(query_limit=13),
    ]:
        with pytest.raises(ValueError):
            expanded(**bad)
    with pytest.raises(ValueError):
        SourcingRunRequest(
            run_id="RUN_MISSING",
            candidate_id="CAND_DEMO",
            source="boss",
            budget_profile="muse-expanded-v1",
            query_limit=12,
        )


def test_twelve_queries_dedup_then_sixty_detail_attempts_and_daily_240(tmp_path):
    from jobagent.schemas.sourcing import SourcingAttemptRequest, SourcingResultRequest
    from jobagent.storage.database import Database
    from jobagent.storage.sourcing_repository import SqliteSourcingRepository

    db = Database(tmp_path / "private.sqlite3")
    db.migrate()
    repo = SqliteSourcingRepository(db)
    for round_number in range(4):
        run_id = f"RUN_{round_number}"
        repo.start_run(expanded(run_id), now=NOW, daily_cap=240)
        listing_ids = []
        for query in range(12):
            attempt_id = f"QUERY_{round_number}_{query}"
            assert repo.reserve(
                SourcingAttemptRequest(
                    attempt_id=attempt_id,
                    run_id=run_id,
                    kind="query",
                    search_term=f"synthetic-{query}",
                ),
                now=NOW,
            ).allowed
            repo.complete(
                SourcingResultRequest(attempt_id=attempt_id, outcome="complete", listing_count=10),
                now=NOW,
            )
            listing_ids.extend(str(i) for i in range(query * 5, query * 5 + 10))
        assert len(set(listing_ids)) == 65  # Host-observed overlaps, no invented count.
        for number, source_id in enumerate(sorted(set(listing_ids))[:60]):
            attempt_id = f"DETAIL_{round_number}_{number}"
            assert repo.reserve(
                SourcingAttemptRequest(
                    attempt_id=attempt_id,
                    run_id=run_id,
                    kind="detail",
                    source_job_id=source_id,
                    url=f"https://www.zhipin.com/job_detail/synthetic-{source_id}.html",
                ),
                now=NOW,
            ).allowed
            repo.complete(SourcingResultRequest(attempt_id=attempt_id, outcome="failed"), now=NOW)
        denied = repo.reserve(
            SourcingAttemptRequest(
                attempt_id=f"DETAIL_DENIED_{round_number}",
                run_id=run_id,
                kind="detail",
                source_job_id="repeated",
                url="https://www.zhipin.com/job_detail/repeated.html",
            ),
            now=NOW,
        )
        assert not denied.allowed and denied.reason in {"round_detail_limit", "daily_detail_limit"}
        assert not repo.reserve(
            SourcingAttemptRequest(
                attempt_id=f"QUERY_DENIED_{round_number}",
                run_id=run_id,
                kind="query",
                search_term="overflow",
            ),
            now=NOW,
        ).allowed
    assert repo.budget("boss", daily_cap=240, now=NOW).read_today == 240
    assert repo.budget("boss", daily_cap=240, now=NOW).remaining == 0
    repo.start_run(expanded("RUN_LAST"), now=NOW, daily_cap=240)
    assert not repo.reserve(
        SourcingAttemptRequest(
            attempt_id="QUERY_AFTER_DAILY_CAP",
            run_id="RUN_LAST",
            kind="query",
            search_term="no_more_budget",
        ),
        now=NOW,
    ).allowed


def test_expanded_query_results_cannot_exceed_first_ten_and_cap_cannot_silently_shrink(tmp_path):
    from jobagent.schemas.sourcing import SourcingAttemptRequest, SourcingResultRequest
    from jobagent.storage.database import Database
    from jobagent.storage.sourcing_repository import SqliteSourcingRepository

    db = Database(tmp_path / "private.sqlite3")
    db.migrate()
    repo = SqliteSourcingRepository(db)
    with pytest.raises(ContractValidationError):
        repo.start_run(expanded(), now=NOW, daily_cap=50)
    repo.start_run(expanded(), now=NOW, daily_cap=240)
    repo.reserve(
        SourcingAttemptRequest(
            attempt_id="QUERY", run_id="RUN_ONE", kind="query", search_term="synthetic"
        ),
        now=NOW,
    )
    with pytest.raises(ContractValidationError):
        repo.complete(
            SourcingResultRequest(attempt_id="QUERY", outcome="complete", listing_count=11), now=NOW
        )


def test_combination_and_intake_plan_accept_twelve_only_under_explicit_profile():
    from jobagent.schemas.job_intake import IntakeStrategyInput
    from jobagent.schemas.lexicon import CombinationInput

    for contract in (CombinationInput, IntakeStrategyInput):
        data = dict(
            candidate_id="CAND_DEMO",
            source="boss",
            baseline_queries=["设计师"],
            query_limit=12,
            budget_profile="muse-expanded-v1",
        )
        if contract is IntakeStrategyInput:
            data["domain"] = "design"
        assert contract.model_validate(data).query_limit == 12
        with pytest.raises(ValueError):
            contract.model_validate({**data, "budget_profile": "conservative"})


def test_expanded_cli_requires_complete_limits_and_reports_selected_daily_cap(tmp_path):
    import json

    from jobagent.cli.app import app
    from tests.cli.test_sourcing import call, runner

    result, output = call(
        tmp_path,
        "sourcing-start",
        dict(
            run_id="RUN_EXPANDED",
            candidate_id="CAND_DEMO",
            source="boss",
            budget_profile="muse-expanded-v1",
            query_limit=12,
            detail_limit=60,
            daily_detail_cap=240,
        ),
    )
    assert result.exit_code == 0, result.output
    assert output["daily_detail_limit"] == 240 and output["query_limit"] == 12
    result = runner.invoke(
        app,
        [
            "jobs",
            "sourcing-budget",
            "--budget-profile",
            "muse-expanded-v1",
            "--daily-detail-cap",
            "240",
            "--database",
            str(tmp_path / "budget.sqlite3"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["boss"]["daily_cap"] == 240


@pytest.mark.parametrize(
    ("salary", "decision"),
    [
        ("CNY 15000-25000 month", "pass"),
        ("CNY 14000-18000 month", "pass"),
        ("CNY 13000-17000 month", "reject"),
        (None, "review"),
        ("USD 18000-25000 month", "review"),
        ("CNY 18000-25000 year", "review"),
    ],
)
def test_host_explicit_upper_bound_salary_contract(salary, decision):
    from jobagent.jobs.hard_filter import HardFilterEngine
    from jobagent.schemas.common import MoneyRange
    from jobagent.schemas.job_intelligence import HardFilterPolicy
    from tests.jobs.test_hard_filter import context, job, requirements

    item = job(salary=salary)
    policy = context(
        minimum_compensation=MoneyRange(currency="CNY", minimum=18000, period="month"),
        compensation_comparison="upper_bound",
    )
    assert (
        HardFilterEngine()
        .evaluate(item, requirements(item.id), policy, HardFilterPolicy())
        .decision.value
        == decision
    )
    assert context().compensation_comparison == "upper_bound"
