"""Check extracted text, order and page budget against a verified variant."""

import hashlib
import io
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from jobagent.optimizer.review import content_digest
from jobagent.schemas.harness import PdfCheckReport, ResumeHeader
from jobagent.schemas.optimizer import ResumeVariant

# List markers carry no claim, so a renderer may put one before any item.
_BULLETS = "•▸▪·◦"


def _normalize(text: str) -> str:
    return "".join(text.split())


def _strip_bullet(text: str) -> str:
    return text[1:] if text[:1] and text[0] in _BULLETS else text


def check_pdf(
    variant: ResumeVariant,
    path: Path,
    *,
    max_pages: int = 2,
    header: ResumeHeader | None = None,
) -> PdfCheckReport:
    if max_pages < 1:
        raise ValueError("max_pages must be positive")
    issues: list[str] = []
    if not variant.verification.passed or not variant.items or not variant.claim_ledger.claims:
        issues.append("variant_not_verified")
    pages = 0
    content = b""
    try:
        content = path.read_bytes()
        reader = PdfReader(io.BytesIO(content), strict=True)
        pages = len(reader.pages)
        extracted = _normalize("\n".join(page.extract_text() or "" for page in reader.pages))
        if pages > max_pages:
            issues.append("page_limit")
        if not extracted:
            issues.append("missing_text")
        remainder = extracted
        if header is not None:
            supplied = _normalize("".join(header.lines))
            if remainder.startswith(supplied):
                remainder = remainder[len(supplied) :]
            else:
                issues.append("header_missing_or_altered")
        for item in variant.items:
            # Section headings are the only permitted content outside verified items.
            heading = _normalize(item.section)
            if remainder.startswith(heading):
                remainder = remainder[len(heading) :]
            remainder = _strip_bullet(remainder)
            text = _normalize(item.text)
            if remainder.startswith(text):
                remainder = remainder[len(text) :]
            else:
                issues.append("item_missing_or_reordered:" + item.id)
                break
        if remainder:
            issues.append("unapproved_or_extra_text")
    except (OSError, ValueError, PdfReadError, KeyError, TypeError):
        issues.append("unreadable_pdf")
    return PdfCheckReport(
        variant_id=variant.id,
        variant_digest=content_digest(variant.model_dump(mode="json")),
        pdf_digest="sha256:" + hashlib.sha256(content).hexdigest(),
        page_count=pages,
        passed=not issues,
        issues=issues,
        header_digest=None if header is None else content_digest(header.model_dump(mode="json")),
    )
