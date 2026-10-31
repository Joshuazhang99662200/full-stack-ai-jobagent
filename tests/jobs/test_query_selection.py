from datetime import UTC, datetime

import pytest

from jobagent.errors import ContractValidationError
from jobagent.schemas.job_intelligence import JobListing


def listing(number, **changes):
    return JobListing.model_validate(
        dict(
            source="boss",
            source_job_id=str(number),
            title="Synthetic Researcher",
            company="Synthetic Organization",
            url=f"https://www.zhipin.com/job_detail/{number}.html",
            collected_at=datetime(2026, 10, 30, tzinfo=UTC),
        )
        | changes
    )


def test_selection_takes_requested_front_rows_and_deduplicates_exact_ids_only():
    from jobagent.jobs.query_selection import select_query_results

    result = select_query_results(
        [listing(1), listing(2), listing(2), listing(3)],
        requested=3,
        source="boss",
        seen={"1"},
    )
    assert result.requested == 3 and result.observed_count == 4
    assert result.taken_count == 3 and result.shortfall == 0
    assert [item.source_job_id for item in result.items] == ["2"]
    assert result.duplicate_ids == ["1", "2"]
    assert all(item.source_job_id != "3" for item in result.items)


def test_shortfall_is_explicit_and_other_sources_are_not_silently_accepted():
    from jobagent.jobs.query_selection import select_query_results

    result = select_query_results([listing(1)], requested=4, source="boss", seen=set())
    assert result.shortfall == 3 and result.taken_count == 1
    with pytest.raises(ContractValidationError, match="source"):
        select_query_results([listing(1, source="zhaopin")], requested=4, source="boss", seen=set())


def test_same_title_company_or_changed_url_never_merge_distinct_platform_ids():
    from jobagent.jobs.query_selection import select_query_results

    one = listing("ID_A")
    two = listing("ID_B", url=str(one.url))
    result = select_query_results([one, two], requested=2, source="boss", seen=set())
    assert [item.source_job_id for item in result.items] == ["ID_A", "ID_B"]
