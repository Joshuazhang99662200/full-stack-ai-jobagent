"""Independent Python reference adaptation of two Career Ops public providers."""

import hashlib
import html
import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit

from pydantic import HttpUrl, ValidationError

from jobagent.errors import ContractValidationError
from jobagent.schemas.job_intelligence import JobListing, JobSearchQuery, SourceJobRecord
from jobagent.schemas.jobs import RecruiterInfo
from jobagent.schemas.public_careers import PublicCareerBoard, PublicCareerItem, PublicCareerPage


class _PostingHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.hidden = tag
        if self.hidden is None and tag in {"p", "div", "br", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == self.hidden:
            self.hidden = None
        if self.hidden is None and tag in {"p", "div", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.hidden is None:
            self.parts.append(data)


def greenhouse_text(content: str) -> str:
    # The API commonly entity-encodes its HTML; decode at most two layers.
    parser = _PostingHTML()
    parser.feed(html.unescape(html.unescape(content)))
    parser.close()
    return "\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip())


def identity(source: str, source_job_id: str) -> str:
    value = f"{source.casefold()}\0{source_job_id.casefold()}"
    return "JOB_" + hashlib.sha256(value.encode()).hexdigest()[:16].upper()


def parse_board(board: PublicCareerBoard, body: bytes) -> PublicCareerPage:
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeError) as error:
        raise ContractValidationError("Public board did not return JSON.") from error
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("jobs"), list)
        or payload.get("success") is False
        or payload.get("error")
        or payload.get("errors")
    ):
        raise ContractValidationError("Public board response is malformed or unsuccessful.")
    jobs = payload["jobs"]
    meta = payload.get("meta", {})
    total = meta.get("total") if isinstance(meta, dict) else None
    page = PublicCareerPage(
        raw_returned=len(jobs),
        truncated=bool(
            payload.get("next")
            or payload.get("nextPage")
            or payload.get("hasMore")
            or (isinstance(total, int) and total != len(jobs))
        ),
    )
    for input_index, raw in enumerate(jobs):
        try:
            if not isinstance(raw, dict) or type(raw.get("id")) not in (str, int):
                raise ValueError("Invalid posting")
            posting_id = str(raw["id"])
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,150}", posting_id):
                raise ValueError("Invalid posting identity")
            url = raw.get("absolute_url") if board.provider == "greenhouse" else raw.get("jobUrl")
            if not isinstance(url, str):
                raise ValueError("Posting has no URL")
            parsed = urlsplit(url)
            hosts = {
                "job-boards.greenhouse.io",
                "boards.greenhouse.io",
                "job-boards.eu.greenhouse.io",
                "boards.eu.greenhouse.io",
            }
            expected_path = f"/{board.board}/jobs/{posting_id}"
            if board.provider == "ashby":
                hosts = {"jobs.ashbyhq.com"}
                expected_path = f"/{board.board}/{posting_id}"
            if (
                parsed.scheme != "https"
                or parsed.hostname not in hosts
                or parsed.username
                or parsed.password
                or parsed.port not in (None, 443)
                or parsed.path.rstrip("/") != expected_path
            ):
                raise ValueError("Posting URL does not match configured board and identity")
            location = raw.get("location")
            if isinstance(location, dict):
                location = location.get("name")
            if not isinstance(location, str) or not location.strip():
                location = None
            listing = JobListing(
                source=board.source,
                source_job_id=posting_id,
                title=raw["title"],
                company=board.company,
                location=location,
                url=HttpUrl(url),
                collected_at=datetime.now(UTC),
            )
            description = raw.get(
                "content" if board.provider == "greenhouse" else "descriptionPlain"
            )
            text = ""
            if isinstance(description, str):
                text = (
                    greenhouse_text(description)
                    if board.provider == "greenhouse"
                    else description.strip()
                )
            observation = (
                SourceJobRecord(
                    source=listing.source,
                    source_job_id=posting_id,
                    title=listing.title,
                    company=listing.company,
                    location=location or "Unknown",
                    jd_raw=text,
                    url=listing.url,
                    collected_at=listing.collected_at,
                    completeness="full",
                    access_state="public",
                )
                if text
                else None
            )
            if observation is None:
                page.missing_jd += 1
            page.records.append(
                PublicCareerItem(input_index=input_index, listing=listing, observation=observation)
            )
        except (KeyError, ValueError, TypeError, AttributeError, ValidationError):
            page.invalid += 1
    return page


class PublicCareerAdapter:
    """Read-only ports over the already-accounted response; never hidden network IO."""

    def __init__(self, page: PublicCareerPage) -> None:
        self.page = page

    def search_listings(self, query: JobSearchQuery) -> Sequence[JobListing]:
        return [
            item.listing
            for item in self.page.records
            if query.query.casefold() in item.listing.title.casefold()
        ]

    def search(self, query: JobSearchQuery) -> Sequence[SourceJobRecord]:
        listings = {item.source_job_id for item in self.search_listings(query)}
        return [
            item.observation
            for item in self.page.records
            if item.observation is not None and item.listing.source_job_id in listings
        ]

    def fetch_job(self, source_job_id: str) -> SourceJobRecord:
        for item in self.page.records:
            if item.listing.source_job_id == source_job_id and item.observation is not None:
                return item.observation
        raise ContractValidationError("Posting has no cached complete observation.")

    def fetch(self, listing: JobListing) -> SourceJobRecord:
        result = self.fetch_job(listing.source_job_id)
        if result.source != listing.source or result.url != listing.url:
            raise ContractValidationError("Listing does not match cached observation.")
        return result

    def get_recruiter(self, source_job_id: str) -> RecruiterInfo | None:
        return None
