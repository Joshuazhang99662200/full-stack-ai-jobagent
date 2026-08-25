# ruff: noqa: RUF001, RUF003 - upstream error strings use fullwidth CJK punctuation
import json
import subprocess
from collections.abc import Sequence

import pytest

from jobagent.connectors.liepin import LiepinCliJobSource
from jobagent.errors import InvalidProviderOutputError, UserInterventionRequiredError
from jobagent.jobs.ports import JobDiscoverySource, JobListingSource
from jobagent.schemas.job_intelligence import JobSearchQuery

# Field names and shape captured from a real /mcp/search-job response.
LISTING = {
    "jobId": 85128839,
    "jobType": "2",
    "jobName": "AI 应用产品经理",
    "company": "亚朵集团",
    "location": "闵行区",
    "salary": "15-20k·15薪",
    "education": "本科",
    "workYears": "3年以上",
    "industry": "酒店/民宿",
    "companyTags": ["五险一金", "绩效奖金"],
    "financingStage": "已上市",
    "companySize": "10000人以上",
    "jobDetailUrl": "https://www.liepin.com/job/1985128839.shtml",
}


def runner_for(
    *,
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
    record: list[Sequence[str]] | None = None,
):
    def run(command: Sequence[str]) -> "subprocess.CompletedProcess[str]":
        if record is not None:
            record.append(list(command))
        return subprocess.CompletedProcess(list(command), returncode, stdout, stderr)

    return run


def test_source_is_a_listing_source_not_a_discovery_source() -> None:
    """Liepin search carries no JD text, so it must not claim the fuller port."""
    source = LiepinCliJobSource(runner=runner_for(stdout="[]"))
    assert isinstance(source, JobListingSource)
    assert not isinstance(source, JobDiscoverySource)


def test_delivery_surface_is_not_reachable() -> None:
    source = LiepinCliJobSource(runner=runner_for(stdout="[]"))
    for forbidden in ("apply", "submit", "deliver", "send"):
        assert not hasattr(source, forbidden)


def test_listings_are_mapped_and_apply_is_never_requested() -> None:
    commands: list[Sequence[str]] = []
    source = LiepinCliJobSource(
        runner=runner_for(stdout=json.dumps({"data": {"list": [LISTING]}}), record=commands)
    )

    results = source.search_listings(JobSearchQuery(query="AI Agent 产品负责人", location="上海"))

    assert len(results) == 1
    listing = results[0]
    assert listing.source == "liepin"
    assert listing.source_job_id == "85128839"
    assert listing.title == "AI 应用产品经理"
    assert listing.company == "亚朵集团"
    assert listing.location == "闵行区"
    assert listing.salary_text == "15-20k·15薪"
    assert listing.education == "本科"
    assert listing.work_years == "3年以上"
    assert listing.industry == "酒店/民宿"
    assert listing.company_size == "10000人以上"
    assert listing.financing_stage == "已上市"
    assert listing.company_tags == ["五险一金", "绩效奖金"]
    assert listing.collected_at.tzinfo is not None

    assert commands == [
        [
            "liepin-cli",
            "job",
            "search",
            "--output",
            "json",
            "--job-name",
            "AI Agent 产品负责人",
            "--address",
            "上海",
        ]
    ]
    assert all("apply" not in part for command in commands for part in command)


def test_listing_carries_no_jd_field() -> None:
    """A listing must not grow a jd_raw lookalike that tailoring could trust."""
    source = LiepinCliJobSource(runner=runner_for(stdout=json.dumps([LISTING])))
    listing = source.search_listings(JobSearchQuery())[0]
    assert not hasattr(listing, "jd_raw")


@pytest.mark.parametrize(
    "payload",
    [
        json.dumps([LISTING]),
        json.dumps({"jobs": [LISTING]}),
        json.dumps({"data": {"records": [LISTING]}}),
    ],
)
def test_common_envelope_shapes_are_accepted(payload: str) -> None:
    source = LiepinCliJobSource(runner=runner_for(stdout=payload))
    assert [item.source_job_id for item in source.search_listings(JobSearchQuery())] == ["85128839"]


@pytest.mark.parametrize(
    "stderr",
    ["x-user-token 已过期", "HTTP 401 unauthorized", "请先登录", "触发风控请稍后再试"],
)
def test_platform_states_require_user_intervention(stderr: str) -> None:
    source = LiepinCliJobSource(runner=runner_for(returncode=1, stderr=stderr))
    with pytest.raises(UserInterventionRequiredError) as caught:
        source.search_listings(JobSearchQuery(query="产品经理"))
    assert caught.value.code == "USER_INTERVENTION_REQUIRED"


def test_silent_exit_two_is_user_intervention() -> None:
    """Upstream suppresses its setup guidance when stderr is not a terminal."""
    source = LiepinCliJobSource(runner=runner_for(returncode=2, stderr=""))

    with pytest.raises(UserInterventionRequiredError) as caught:
        source.search_listings(JobSearchQuery(query="产品经理"))

    assert caught.value.details["returncode"] == 2
    assert "liepin-cli setup" in caught.value.details["hint"]


def test_request_failure_exit_one_is_not_disguised_as_intervention() -> None:
    # Upstream writes "错误：请求失败：<detail>"; the fullwidth colon is theirs.
    stderr = "错误：请求失败：timed out"
    source = LiepinCliJobSource(runner=runner_for(returncode=1, stderr=stderr))

    with pytest.raises(InvalidProviderOutputError) as caught:
        source.search_listings(JobSearchQuery(query="产品经理"))

    assert caught.value.details["returncode"] == 1


def test_missing_executable_is_user_intervention() -> None:
    def run(command: Sequence[str]) -> "subprocess.CompletedProcess[str]":
        raise FileNotFoundError(command[0])

    with pytest.raises(UserInterventionRequiredError, match="not installed"):
        LiepinCliJobSource(runner=run).search_listings(JobSearchQuery())


def test_timeout_is_user_intervention_not_a_retry() -> None:
    def run(command: Sequence[str]) -> "subprocess.CompletedProcess[str]":
        raise subprocess.TimeoutExpired(list(command), 120)

    with pytest.raises(UserInterventionRequiredError, match="did not respond"):
        LiepinCliJobSource(runner=run).search_listings(JobSearchQuery())


def test_non_json_output_is_invalid_provider_output() -> None:
    source = LiepinCliJobSource(runner=runner_for(stdout="not json at all"))
    with pytest.raises(InvalidProviderOutputError):
        source.search_listings(JobSearchQuery())


def test_listing_missing_required_fields_is_rejected() -> None:
    incomplete = {"jobId": "lp-1", "jobName": "PM"}
    source = LiepinCliJobSource(runner=runner_for(stdout=json.dumps([incomplete])))
    with pytest.raises(InvalidProviderOutputError) as caught:
        source.search_listings(JobSearchQuery())
    assert caught.value.details["missing_fields"] == ["company", "url"]


def test_decode_handles_the_windows_ansi_codepage() -> None:
    """Upstream emits cp936 bytes when stdout is a pipe, not UTF-8."""
    from jobagent.connectors.liepin import _decode

    text = "AI大模型应用工程师"
    assert _decode(text.encode("utf-8")) == text
    assert _decode(text.encode("gb18030")) == text
