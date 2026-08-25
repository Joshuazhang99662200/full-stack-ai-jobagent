"""Fetch a job description from a board that serves it in public HTML.

Behaviour comes from the source manifest's `detail` section, so supporting a new
board is a YAML file rather than a new rules constant here.

One posting at a time, triggered by a person. This is not a crawler. Boards differ
in how strict their terms are; batch scanning is out of scope for all of them.
"""

import urllib.error
import urllib.request
from datetime import UTC, datetime

from jobagent.connectors.extraction import extract_bounded
from jobagent.errors import ContractValidationError, UserInterventionRequiredError
from jobagent.schemas.job_intelligence import JobListing, SourceJobRecord
from jobagent.schemas.sources import SourceManifest

_USER_AGENT = "Mozilla/5.0 (compatible; JobAgent/1.0; +human-triggered single fetch)"
_TIMEOUT_SECONDS = 30


class PublicPageJobDetailFetcher:
    """Turn a `JobListing` into a full `SourceJobRecord` from a public page."""

    def __init__(self, manifest: SourceManifest, *, opener: object | None = None) -> None:
        from jobagent.connectors.factory import extraction_rules

        self._rules = extraction_rules(manifest)
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
