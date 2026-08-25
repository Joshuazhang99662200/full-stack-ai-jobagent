from datetime import UTC, datetime

import pytest

from jobagent.connectors.extraction import ExtractionRules, extract_bounded
from jobagent.connectors.gated import GATED_SOURCES, gated_source
from jobagent.connectors.public_pages import PublicPageJobDetailFetcher
from jobagent.errors import (
    ContractValidationError,
    InvalidProviderOutputError,
    UserInterventionRequiredError,
)
from jobagent.schemas.job_intelligence import JobListing

RULES = ExtractionRules(
    source="test",
    start_headings=("职位描述",),
    stop_headings=("公司简介", "猜你喜欢"),
)


def listing(source: str = "zhaopin") -> JobListing:
    return JobListing(
        source=source,
        source_job_id="J1",
        title="产品经理",
        company="示例科技",
        url="https://example.test/job/1",
        collected_at=datetime.now(UTC),
    )


def page(body: str) -> str:
    return f"<html><body>{body}</body></html>"


def test_extraction_stops_at_the_first_trailing_section() -> None:
    """The rails and blurbs after the JD must never reach jd_raw."""
    html = page(
        "<div>职位描述</div>"
        "<p>1、负责多智能体产品架构与 Skill 体系建设,推动大模型能力在金融场景落地。</p>"
        "<p>2、独立产出 PRD 与原型,与算法及研发团队对齐技术细节。</p>"
        "<div>公司简介</div><p>我们是一家很棒的公司,员工众多,福利优厚,欢迎加入我们。</p>"
        "<div>猜你喜欢</div><p>其他推荐职位</p>"
    )
    jd = extract_bounded(html, RULES, job_id="J1")

    assert "多智能体产品架构" in jd
    assert "很棒的公司" not in jd
    assert "其他推荐职位" not in jd


def test_gate_marker_is_user_intervention_not_a_short_body() -> None:
    html = page("<div>请登录</div><p>登录查看完整内容</p>")

    with pytest.raises(UserInterventionRequiredError) as caught:
        extract_bounded(html, RULES, job_id="J1")

    assert caught.value.details["source"] == "test"
    assert caught.value.details["gate_marker"]


def test_a_stub_body_behind_a_gate_is_reported_as_a_gate() -> None:
    """A gate rendered in place of the JD leaves a short body, not a missing one."""
    html = page("<div>职位描述</div><p>请登录</p>")

    with pytest.raises(UserInterventionRequiredError):
        extract_bounded(html, RULES, job_id="J1")


def test_short_body_without_a_gate_is_invalid_output() -> None:
    html = page("<div>职位描述</div><p>略</p>")

    with pytest.raises(InvalidProviderOutputError, match="too short"):
        extract_bounded(html, RULES, job_id="J1")


def test_missing_section_is_invalid_output() -> None:
    with pytest.raises(InvalidProviderOutputError, match="no job description"):
        extract_bounded(page("<p>无关内容</p>"), RULES, job_id="J1")


def test_zhaopin_fetcher_reads_a_public_posting() -> None:
    body = page(
        "<div>职位描述</div>"
        "<p>1、负责大模型产品设计,推动技术在金融投研场景的深度应用与落地。</p>"
        "<p>2、优化 Prompt 与智能体机制,提升输出的专业性与可靠性。</p>"
        "<div>职位福利</div><p>五险一金</p>"
    )
    fetcher = PublicPageJobDetailFetcher("zhaopin", opener=_opener_for(body))

    record = fetcher.fetch(listing("zhaopin"))

    assert record.source == "zhaopin"
    assert "大模型产品设计" in record.jd_raw
    assert "五险一金" not in record.jd_raw


def test_linkedin_fetcher_reads_the_guest_posting() -> None:
    body = page(
        "<div>About the job</div><p>Own the roadmap for our agent platform team.</p>"
        "<div>Seniority level</div><p>Mid-Senior</p>"
    )
    fetcher = PublicPageJobDetailFetcher("linkedin", opener=_opener_for(body))

    record = fetcher.fetch(listing("linkedin"))

    assert "agent platform" in record.jd_raw
    assert "Mid-Senior" not in record.jd_raw


def test_fetcher_rejects_a_listing_from_another_source() -> None:
    fetcher = PublicPageJobDetailFetcher("zhaopin", opener=_opener_for(page("x")))
    with pytest.raises(ContractValidationError, match="does not handle"):
        fetcher.fetch(listing("linkedin"))


def test_unknown_source_has_no_rules() -> None:
    with pytest.raises(ContractValidationError, match="No public-page extraction rules"):
        PublicPageJobDetailFetcher("nope")


@pytest.mark.parametrize("name", sorted(GATED_SOURCES))
def test_gated_sources_pause_and_offer_a_manual_route(name: str) -> None:
    """A bot-detection gate is a handover, never something to work around."""
    source = gated_source(name)
    assert source is not None

    with pytest.raises(UserInterventionRequiredError) as caught:
        source.fetch(listing(name))

    details = caught.value.details
    assert details["source"] == name
    assert details["gate"]
    assert "ingest-jd" in details["manual_route"]
    assert "不绕过" in details["never"]


def test_gated_source_never_returns_a_record() -> None:
    source = gated_source("boss")
    assert source is not None
    assert not hasattr(source, "search_listings")


def test_unknown_source_is_not_gated() -> None:
    assert gated_source("liepin") is None


def _opener_for(body: str):
    class Response:
        headers = type("H", (), {"get_content_charset": staticmethod(lambda: "utf-8")})()

        def read(self) -> bytes:
            return body.encode("utf-8")

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *exc: object) -> None:
            return None

    def opener(request: object, timeout: int) -> Response:
        return Response()

    return opener
