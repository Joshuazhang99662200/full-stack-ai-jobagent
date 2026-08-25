"""Fetch one Liepin job description from its public detail page.

Liepin serves the JD in server-rendered HTML on the public detail page, so no
login, browser automation or cookie reuse is involved. Extraction is deliberately
**bounded**: the JD block is cut at the first trailing section, because the raw
page also carries the company blurb, Liepin's anti-fraud notice and a
"recommended jobs" rail. Splicing those into `jd_raw` would silently corrupt
requirement extraction, so a truncated or missing block fails loudly instead.

One job at a time, triggered by a person. This is not a crawler.
"""

import html
import re
import urllib.error
import urllib.request
from datetime import UTC, datetime

from jobagent.errors import (
    ContractValidationError,
    InvalidProviderOutputError,
    UserInterventionRequiredError,
)
from jobagent.jobs.recruiter import RecruiterClassifier
from jobagent.schemas.job_intelligence import JobListing, SourceJobRecord
from jobagent.schemas.jobs import RecruiterInfo

SOURCE_NAME = "liepin"
_USER_AGENT = "Mozilla/5.0 (compatible; JobAgent/1.0; +human-triggered single fetch)"
_TIMEOUT_SECONDS = 30

# The JD sits under this heading; everything from the first trailing heading on
# belongs to other page sections and must not enter jd_raw.
_JD_HEADING = "职位介绍"
_TRAILING_HEADINGS = ("其他信息", "公司简介", "猎聘温馨提示", "猜你喜欢", "举报")

# Markers that mean the page withheld the JD. Never save a partial JD.
_WITHHELD_MARKERS = ("登录查看", "请登录", "登录后查看", "安全验证", "验证码", "访问过于频繁")

_MIN_JD_LENGTH = 30

# The job's own recruiter card. Recommended-job cards render the same markup, so
# extraction is bounded to this block rather than searching the whole page.
_RECRUITER_BLOCK = 'class="recruiter-container"'
_RECRUITER_BLOCK_LIMIT = 2000
# The card ends at the chat control; anything past it belongs to other widgets.
_RECRUITER_STOP_TOKENS = ("聊一聊", "立即沟通", "收藏")
# Presence badges are not part of the recruiter's identity.
_RECRUITER_NOISE = ("在线", "已认证", "刚刚活跃")


def _strip_markup(fragment: str) -> str:
    without_scripts = re.sub(r"<(script|style)\b.*?</\1>", " ", fragment, flags=re.S | re.I)
    with_breaks = re.sub(r"<(br|/p|/div|/li)\s*/?>", "\n", without_scripts, flags=re.I)
    text = re.sub(r"<[^>]+>", "", with_breaks)
    text = html.unescape(text)
    lines = [" ".join(line.split()) for line in text.split("\n")]
    return "\n".join(line for line in lines if line and not line.startswith("-->"))


class LiepinJobDetailFetcher:
    """Turn a `JobListing` into a full `SourceJobRecord` by reading its detail page."""

    def __init__(self, *, opener: object | None = None) -> None:
        self._opener = opener

    def fetch(self, listing: JobListing) -> SourceJobRecord:
        if listing.source != SOURCE_NAME:
            raise ContractValidationError(
                "This fetcher only handles Liepin listings.",
                details={"source": listing.source, "expected": SOURCE_NAME},
            )
        page = self._read(str(listing.url))
        jd_raw = self._extract_jd(page, listing)
        return SourceJobRecord(
            source=listing.source,
            source_job_id=listing.source_job_id,
            title=listing.title,
            company=listing.company,
            location=listing.location or "未标注",
            salary_text=listing.salary_text,
            jd_raw=jd_raw,
            recruiter=self._extract_recruiter(page, listing),
            url=listing.url,
            collected_at=datetime.now(UTC),
        )

    @staticmethod
    def _extract_recruiter(page: str, listing: JobListing) -> RecruiterInfo | None:
        """Read the recruiter card, bounded to the job's own block.

        The page also renders recruiter cards for the "recommended jobs" rail, so
        an unbounded search would attribute a different recruiter to this job.
        """
        start = page.find(_RECRUITER_BLOCK)
        if start < 0:
            return None
        block = page[start : start + _RECRUITER_BLOCK_LIMIT]

        # The card renders as a flat run of short lines, e.g.
        #   直招: 孙女士 / 3小时前在线 / 已认证 / 宁波银行 / 聊一聊
        #   猎头: 许先生 / 5天前在线 / 已认证 / 猎头 / · 北京优九人才咨询有限公司 / 聊一聊
        # Class selectors proved brittle here, so read that sequence instead.
        lines = [
            line
            for line in (part.strip() for part in _strip_markup(block).split("\n"))
            if line and "<" not in line and not line.startswith("class=")
        ]
        tokens: list[str] = []
        for line in lines:
            if line in _RECRUITER_STOP_TOKENS:
                break
            if any(noise in line for noise in _RECRUITER_NOISE):
                continue
            tokens.append(line)
        if not tokens:
            return None

        name = tokens[0]
        # Everything after the name is the affiliation; Liepin writes 猎头
        # explicitly when the poster is an agency rather than the employer.
        affiliation = " ".join(tokens[1:]).strip()
        organization = affiliation.split("·")[-1].strip() or None

        return RecruiterClassifier().classify(
            name=name,
            title=affiliation or None,
            organization=organization,
            hiring_company=listing.company,
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
                "Liepin refused the detail request; a person must open the page.",
                details={"source": SOURCE_NAME, "url": url, "status_code": error.code},
            ) from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise UserInterventionRequiredError(
                "Liepin's detail page could not be reached.",
                details={"source": SOURCE_NAME, "url": url},
            ) from error

    @staticmethod
    def _extract_jd(page: str, listing: JobListing) -> str:
        text = _strip_markup(page)
        start = text.find(_JD_HEADING)
        if start < 0:
            withheld = [marker for marker in _WITHHELD_MARKERS if marker in text]
            if withheld:
                raise UserInterventionRequiredError(
                    "Liepin withheld the job description behind a gate.",
                    details={"source": SOURCE_NAME, "job_id": listing.source_job_id},
                )
            raise InvalidProviderOutputError(
                "The Liepin detail page contained no job description section.",
                details={"source": SOURCE_NAME, "job_id": listing.source_job_id},
            )

        body = text[start + len(_JD_HEADING) :]
        cuts = [index for index in (body.find(h) for h in _TRAILING_HEADINGS) if index > 0]
        if cuts:
            body = body[: min(cuts)]

        jd_raw = body.strip()
        if len(jd_raw) < _MIN_JD_LENGTH:
            raise InvalidProviderOutputError(
                "The extracted Liepin job description was too short to trust.",
                details={
                    "source": SOURCE_NAME,
                    "job_id": listing.source_job_id,
                    "length": len(jd_raw),
                },
            )
        return jd_raw
