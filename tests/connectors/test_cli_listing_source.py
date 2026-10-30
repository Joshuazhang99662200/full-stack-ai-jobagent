import json
import subprocess
from collections.abc import Sequence
from typing import Any

import pytest

from jobagent.connectors.cli_source import CliListingSource
from jobagent.errors import InvalidProviderOutputError, UserInterventionRequiredError
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


@pytest.mark.parametrize(
    "payload,reason",
    [
        ({"code": 429001, "data": {"jobs": []}}, "risk_control"),
        ({"code": "429", "jobs": []}, "risk_control"),
        ({"code": 401, "jobs": []}, "login_required"),
        ({"data": {"errorCode": 429001, "jobs": []}}, "risk_control"),
        ({"success": False, "message": "验证码", "jobs": []}, "verification_required"),
        ({"error": {"message": "rate limited"}, "jobs": []}, "risk_control"),
        ({"code": 429001, "error": {"code": "UNKNOWN_FAILURE"}}, "risk_control"),
    ],
)
def test_business_intervention_never_becomes_zero_results_or_retries(payload, reason) -> None:
    calls = []

    def runner(command, timeout):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, json.dumps(payload).encode(), b"")

    with pytest.raises(UserInterventionRequiredError) as caught:
        CliListingSource(LIEPIN, runner=runner).search_listings(JobSearchQuery(query="Engineer"))
    assert caught.value.details["intervention_reason"] == reason
    assert len(calls) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"code": 700001, "jobs": []},
        {"success": False, "jobs": []},
        {"error": {"code": "UNKNOWN_FAILURE"}, "jobs": []},
        {"status": "failed", "data": {"jobs": []}},
    ],
)
def test_unknown_business_failure_is_not_a_successful_empty_search(payload) -> None:
    with pytest.raises(InvalidProviderOutputError):
        source_returning(payload).search_listings(JobSearchQuery(query="Engineer"))


@pytest.mark.parametrize("code", [0, "0", 200, "200"])
def test_explicit_success_envelope_preserves_empty_search(code) -> None:
    assert source_returning({"code": code, "data": {"jobs": []}}).search_listings(
        JobSearchQuery(query="Researcher")
    ) == []


def test_nonzero_exit_with_structured_rate_error_is_not_retried() -> None:
    calls = []

    def runner(command, timeout):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1, b'{"code":429001,"data":{"jobs":[]}}', b"")

    with pytest.raises(UserInterventionRequiredError) as caught:
        CliListingSource(LIEPIN, runner=runner).search_listings(JobSearchQuery(query="Designer"))
    assert caught.value.details["intervention_reason"] == "risk_control"
    assert len(calls) == 1


def test_job_text_does_not_become_a_provider_intervention() -> None:
    listing = search(row(jobName="Captcha and rate limit reliability researcher"))[0]
    assert listing.title == "Captcha and rate limit reliability researcher"


def test_business_failure_diagnostics_do_not_echo_provider_contents() -> None:
    marker = "SYNTHETIC_PRIVATE_PROVIDER_CONTENT"
    with pytest.raises(InvalidProviderOutputError) as caught:
        source_returning({"success": False, "message": marker, "jobs": []}).search_listings(
            JobSearchQuery(query="Analyst")
        )
    assert marker not in str(caught.value)
    assert marker not in json.dumps(caught.value.details)
