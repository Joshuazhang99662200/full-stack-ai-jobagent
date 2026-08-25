"""Job-description fetchers for boards that serve the JD publicly.

Verified by probing real postings: 智联招聘 renders the JD server-side under
「职位描述」, and LinkedIn's guest posting endpoint carries the full description.
Neither requires login, browser automation or cookie reuse.

One posting at a time, triggered by a person. This is not a crawler. LinkedIn's
terms are stricter than the Chinese boards', so batch scanning is out of scope
there in particular.
"""

import urllib.error
import urllib.request
from datetime import UTC, datetime

from jobagent.connectors.extraction import ExtractionRules, extract_bounded
from jobagent.errors import ContractValidationError, UserInterventionRequiredError
from jobagent.schemas.job_intelligence import JobListing, SourceJobRecord

_USER_AGENT = "Mozilla/5.0 (compatible; JobAgent/1.0; +human-triggered single fetch)"
_TIMEOUT_SECONDS = 30

ZHAOPIN_RULES = ExtractionRules(
    source="zhaopin",
    start_headings=("职位描述", "岗位职责", "职位信息"),
    stop_headings=("职位福利", "公司介绍", "公司简介", "工作地址", "举报", "猜你喜欢", "相似职位"),
)

LINKEDIN_RULES = ExtractionRules(
    source="linkedin",
    start_headings=("About the job", "Job description", "role at"),
    stop_headings=(
        "Show more",
        "Seniority level",
        "Referrals increase",
        "Featured Benefits",
        "See who you know",
    ),
    # LinkedIn's own wording when it withholds a posting from guests.
    gate_markers=("authwall", "Sign in to view", "Join LinkedIn to", "unavailable"),
)

_RULES: dict[str, ExtractionRules] = {
    ZHAOPIN_RULES.source: ZHAOPIN_RULES,
    LINKEDIN_RULES.source: LINKEDIN_RULES,
}


class PublicPageJobDetailFetcher:
    """Turn a `JobListing` into a full `SourceJobRecord` from a public page."""

    def __init__(self, source: str, *, opener: object | None = None) -> None:
        rules = _RULES.get(source)
        if rules is None:
            raise ContractValidationError(
                "No public-page extraction rules are registered for this source.",
                details={"source": source, "known": sorted(_RULES)},
            )
        self._rules = rules
        self._opener = opener

    @property
    def source(self) -> str:
        return self._rules.source

    def fetch(self, listing: JobListing) -> SourceJobRecord:
        if listing.source != self._rules.source:
            raise ContractValidationError(
                "This fetcher does not handle that source.",
                details={"source": listing.source, "expected": self._rules.source},
            )
        page = self._read(str(listing.url))
        jd_raw = extract_bounded(page, self._rules, job_id=listing.source_job_id)
        return SourceJobRecord(
            source=listing.source,
            source_job_id=listing.source_job_id,
            title=listing.title,
            company=listing.company,
            location=listing.location or "未标注",
            salary_text=listing.salary_text,
            jd_raw=jd_raw,
            url=listing.url,
            collected_at=datetime.now(UTC),
        )

    def _read(self, url: str) -> str:
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            opener = self._opener or urllib.request.urlopen
            with opener(request, timeout=_TIMEOUT_SECONDS) as response:  # type: ignore[operator]
                charset = response.headers.get_content_charset() or "utf-8"
                body: bytes = response.read()
                return body.decode(charset, errors="replace")
        except urllib.error.HTTPError as error:
            # 403/429 mean the platform is gating us. Never retry around that.
            raise UserInterventionRequiredError(
                "The platform refused the detail request; a person must open the page.",
                details={"source": self._rules.source, "url": url, "status_code": error.code},
            ) from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise UserInterventionRequiredError(
                "The detail page could not be reached.",
                details={"source": self._rules.source, "url": url},
            ) from error
