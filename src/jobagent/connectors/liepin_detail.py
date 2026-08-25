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
from jobagent.schemas.job_intelligence import JobListing, SourceJobRecord

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
