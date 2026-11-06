"""Check extracted text, order and page budget against a verified variant."""

import io
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from jobagent.digest import bytes_digest, canonical_digest
from jobagent.harness.artifact_rules import (
    compare_variant_text,
    internal_note_issues,
    pdf_review_issues,
)
from jobagent.schemas.harness import PdfCheckReport, ResumeHeader
from jobagent.schemas.optimizer import ResumeVariant


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
    pages = 0
    content = b""
    try:
        content = path.read_bytes()
        reader = PdfReader(io.BytesIO(content), strict=True)
        pages = len(reader.pages)
        extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
        issues.extend(pdf_review_issues(reader))
        issues.extend(internal_note_issues(extracted))
        issues.extend(compare_variant_text(extracted, variant, header))
        if pages > max_pages:
            issues.append("page_limit")
    except (OSError, ValueError, PdfReadError, KeyError, TypeError):
        issues.append("unreadable_pdf")
    return PdfCheckReport(
        variant_id=variant.id,
        variant_digest=canonical_digest(variant.model_dump(mode="json")),
        pdf_digest=bytes_digest(content),
        page_count=pages,
        passed=not issues,
        issues=issues,
        header_digest=None if header is None else canonical_digest(header.model_dump(mode="json")),
    )
