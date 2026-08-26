import json
import subprocess
from collections.abc import Sequence
from typing import Any

import pytest

from jobagent.connectors.cli_source import CliListingSource
from jobagent.schemas.job_intelligence import JobListing, JobSearchQuery
from jobagent.sources import SourceRegistry

# The liepin manifest declares the candidate keys; nothing here is hardcoded.
LIEPIN = SourceRegistry.default().get("liepin")


def source_returning(payload: object) -> CliListingSource:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def runner(command: Sequence[str], timeout: int) -> "subprocess.CompletedProcess[bytes]":
        return subprocess.CompletedProcess(list(command), 0, body, b"")

    return CliListingSource(LIEPIN, runner=runner)


def row(**extra: Any) -> dict[str, Any]:
    return {
        "jobId": "1976319881",
        "jobName": "大模型产品经理",
        "company": "宁波银行",
        "jobDetailUrl": "https://www.liepin.com/job/1976319881.shtml",
        **extra,
    }


def search(*rows: dict[str, Any]) -> list[JobListing]:
    return source_returning({"jobs": list(rows)}).search_listings(JobSearchQuery(query="产品经理"))


def test_integer_job_kind_is_coerced_to_str() -> None:
    """Upstream sends a headhunter posting's kind as a bare int."""
    listing = search(row(jobKind=1))[0]

    assert listing.job_kind == "1"
    assert isinstance(listing.job_kind, str)


def test_string_job_kind_is_preserved_verbatim() -> None:
    """A direct-employer posting arrives as a string and must not be renumbered."""
    listing = search(row(jobType="2"))[0]

    assert listing.job_kind == "2"


@pytest.mark.parametrize("key", ["jobKind", "jobType", "job_kind"])
def test_every_declared_candidate_key_is_accepted(key: str) -> None:
    listing = search(row(**{key: "2"}))[0]

    assert listing.job_kind == "2"


def test_absent_job_kind_stays_none() -> None:
    listing = search(row())[0]

    assert listing.job_kind is None


def test_absent_job_kind_is_never_replaced_by_a_default() -> None:
    """Guessing this value is what upstream explicitly warns against."""
    listing = search(row())[0]
    dumped = listing.model_dump()

    assert dumped["job_kind"] is None
    assert dumped["job_kind"] not in {"1", "2", 1, 2, ""}
    assert JobListing.model_fields["job_kind"].get_default() is None


def test_other_listing_fields_still_map() -> None:
    listing = search(row(salary="40-60k", jobKind=1))[0]

    assert listing.source == "liepin"
    assert listing.source_job_id == "1976319881"
    assert listing.salary_text == "40-60k"
    assert listing.job_kind == "1"
