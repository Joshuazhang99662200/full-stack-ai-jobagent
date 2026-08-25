"""Platforms whose job descriptions are not publicly reachable.

BOSS 直聘 redirects an unauthenticated detail request to a security-verification
page, and 前程无忧 answers with an Aliyun WAF challenge. These are deliberate
bot-detection gates, not transient faults.

Reaching the JD anyway would require fingerprint spoofing, stealth browsers,
proxy rotation or CAPTCHA solving. This project does not do that: those states
translate to `USER_INTERVENTION_REQUIRED` and hand control back to the person,
who can open the posting in their own browser and supply the text.

Modelling them explicitly — rather than leaving them unimplemented — keeps the
workflow complete and makes the boundary visible instead of silent.
"""

from dataclasses import dataclass

from jobagent.errors import UserInterventionRequiredError
from jobagent.schemas.job_intelligence import JobListing, SourceJobRecord


@dataclass(frozen=True)
class GateReport:
    source: str
    display_name: str
    gate: str
    detail: str


BOSS_ZHIPIN = GateReport(
    source="boss",
    display_name="BOSS 直聘",
    gate="security_verification_redirect",
    detail="未登录的职位详情请求会被 302 到 web/passport/zp/security.html 安全验证页。",
)

QIANCHENG_51JOB = GateReport(
    source="51job",
    display_name="前程无忧",
    gate="waf_challenge",
    detail="搜索与详情接口返回阿里云 WAF 挑战(aliyun_waf_aa + 混淆 JS)。",
)

GATED_SOURCES: dict[str, GateReport] = {
    BOSS_ZHIPIN.source: BOSS_ZHIPIN,
    QIANCHENG_51JOB.source: QIANCHENG_51JOB,
}


class GatedJobSource:
    """Report a platform gate as a typed pause, with a usable manual route."""

    def __init__(self, report: GateReport) -> None:
        self._report = report

    @property
    def source(self) -> str:
        return self._report.source

    def fetch(self, listing: JobListing) -> SourceJobRecord:
        raise self.gate_error(job_id=listing.source_job_id, url=str(listing.url))

    def gate_error(
        self, *, job_id: str | None = None, url: str | None = None
    ) -> UserInterventionRequiredError:
        report = self._report
        return UserInterventionRequiredError(
            f"{report.display_name} does not expose this job description publicly.",
            details={
                "source": report.source,
                "job_id": job_id,
                "url": url,
                "gate": report.gate,
                "detail": report.detail,
                "manual_route": (
                    "在你自己的浏览器里打开该职位,复制 JD 正文,"
                    "然后用 `jobagent jobs ingest-jd` 提交。"
                ),
                "never": "不绕过验证、不伪装指纹、不轮换账号或代理。",
            },
        )


def gated_source(name: str) -> GatedJobSource | None:
    report = GATED_SOURCES.get(name)
    return None if report is None else GatedJobSource(report)
