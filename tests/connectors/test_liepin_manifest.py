# ruff: noqa: RUF001 - Liepin page copy uses fullwidth CJK punctuation
import urllib.error
from datetime import UTC, datetime
from typing import Any

import pytest

from jobagent.connectors.public_pages import PublicPageJobDetailFetcher
from jobagent.errors import (
    ContractValidationError,
    InvalidProviderOutputError,
    UserInterventionRequiredError,
)
from jobagent.schemas.job_intelligence import JobListing
from jobagent.sources import SourceRegistry

# The liepin manifest's `detail` section drives extraction; nothing here is
# hardcoded per platform any more.
LIEPIN = SourceRegistry.default().get("liepin")


def fetcher(opener: object) -> PublicPageJobDetailFetcher:
    return PublicPageJobDetailFetcher(LIEPIN, opener=opener)


LISTING = JobListing(
    source="liepin",
    source_job_id="1976319881",
    title="大模型产品经理（投研方向）",
    company="宁波银行",
    location="上海-浦东新区",
    url="https://www.liepin.com/job/1976319881.shtml",
    salary_text="40-60k",
    collected_at=datetime.now(UTC),
)

# Mirrors the real page: the JD is followed by other sections that must be cut.
PAGE = """
<html><body>
<div class="job-intro"><h2>职位介绍</h2>
<p>1、负责大模型产品设计工作，推动大模型技术在金融场景的深度应用。</p>
<p>2、针对金融领域专业需求，优化Prompt和智能体机制。</p>
</div>
<div class="other"><h2>其他信息</h2><p>语言要求：英语、普通话</p></div>
<div class="comp"><h2>公司简介</h2><p>宁波银行股份有限公司诚聘</p></div>
<div class="tip"><h2>猎聘温馨提示：</h2><p>如您发现平台内招聘方存在违规行为</p></div>
<div class="rec"><h2>猜你喜欢</h2><p>AI Infra 产品经理</p></div>
</body></html>
"""


class FakeResponse:
    def __init__(self, body: str, charset: str = "utf-8") -> None:
        self._body = body.encode(charset)
        self._charset = charset

    def read(self) -> bytes:
        return self._body

    @property
    def headers(self) -> Any:
        charset = self._charset

        class _Headers:
            @staticmethod
            def get_content_charset() -> str:
                return charset

        return _Headers()

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def opener_for(body: str):
    def opener(request: Any, timeout: int = 0) -> FakeResponse:
        return FakeResponse(body)

    return opener


def test_jd_is_extracted_and_bounded_at_the_next_section() -> None:
    record = fetcher(opener_for(PAGE)).fetch(LISTING)

    assert "负责大模型产品设计工作" in record.jd_raw
    assert "优化Prompt和智能体机制" in record.jd_raw
    # Everything after the JD block must be excluded.
    for leaked in ("语言要求", "宁波银行股份有限公司诚聘", "猎聘温馨提示", "AI Infra 产品经理"):
        assert leaked not in record.jd_raw


def test_listing_fields_are_carried_into_the_full_record() -> None:
    record = fetcher(opener_for(PAGE)).fetch(LISTING)

    assert record.source_job_id == "1976319881"
    assert record.title == "大模型产品经理（投研方向）"
    assert record.company == "宁波银行"
    assert record.salary_text == "40-60k"
    assert str(record.url) == str(LISTING.url)
    assert record.collected_at.tzinfo is not None


@pytest.mark.parametrize("marker", ["登录查看完整内容", "请登录", "安全验证", "访问过于频繁"])
def test_gated_page_requires_a_human_instead_of_saving_a_partial_jd(marker: str) -> None:
    page = f"<html><body><div>{marker}</div></body></html>"

    with pytest.raises(UserInterventionRequiredError):
        fetcher(opener_for(page)).fetch(LISTING)


def test_missing_jd_section_is_not_silently_accepted() -> None:
    page = "<html><body><div>公司简介 宁波银行</div></body></html>"

    with pytest.raises(InvalidProviderOutputError, match="no job description"):
        fetcher(opener_for(page)).fetch(LISTING)


def test_suspiciously_short_jd_is_rejected() -> None:
    page = "<html><body><h2>职位介绍</h2><p>详见沟通</p><h2>其他信息</h2></body></html>"

    with pytest.raises(InvalidProviderOutputError, match="too short"):
        fetcher(opener_for(page)).fetch(LISTING)


@pytest.mark.parametrize("status", [403, 429, 404])
def test_http_gating_is_user_intervention_not_a_retry(status: int) -> None:
    def opener(request: Any, timeout: int = 0) -> FakeResponse:
        raise urllib.error.HTTPError(str(LISTING.url), status, "blocked", {}, None)  # type: ignore[arg-type]

    with pytest.raises(UserInterventionRequiredError) as caught:
        fetcher(opener).fetch(LISTING)

    assert caught.value.details["status_code"] == status


def test_non_liepin_listing_is_rejected() -> None:
    other = LISTING.model_copy(update={"source": "mock-alpha"})

    with pytest.raises(ContractValidationError):
        fetcher(opener_for(PAGE)).fetch(other)
