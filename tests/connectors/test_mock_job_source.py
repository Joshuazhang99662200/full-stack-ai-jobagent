from pathlib import Path

import pytest

from jobagent.connectors.mock import MockJobSource
from jobagent.errors import JobNotFoundError
from jobagent.schemas.job_intelligence import JobSearchQuery

ROOT = Path(__file__).parents[2]
FIXTURE = ROOT / "src" / "jobagent" / "connectors" / "fixtures" / "jobs.json"


def source() -> MockJobSource:
    return MockJobSource.from_path(FIXTURE)


def test_search_uses_case_insensitive_and_tokens_with_stable_order() -> None:
    results = source().search(JobSearchQuery(query="PYTHON api"))

    assert [item.source_job_id for item in results] == ["alpha-001", "beta-991"]


def test_search_applies_exact_optional_filters() -> None:
    results = source().search(
        JobSearchQuery(
            company="Example Labs",
            location="Copenhagen",
            source_job_id="beta-991",
        )
    )

    assert [item.source_job_id for item in results] == ["beta-991"]


def test_fetch_and_recruiter_are_independent_reads() -> None:
    connector = source()

    job = connector.fetch_job("alpha-001")
    recruiter = connector.get_recruiter("alpha-001")

    assert job.title == "Python Platform Engineer"
    assert recruiter is not None and recruiter.name == "Mira Jensen"


def test_unknown_source_job_returns_typed_error() -> None:
    with pytest.raises(JobNotFoundError) as captured:
        source().fetch_job("missing-001")

    assert captured.value.code == "JOB_NOT_FOUND"


def test_phase_three_source_has_no_application_side_effect_methods() -> None:
    connector = source()

    assert not hasattr(connector, "preview_application")
    assert not hasattr(connector, "submit_application")
