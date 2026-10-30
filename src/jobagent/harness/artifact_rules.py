"""Shared, deterministic checks on employer-facing text and PDF containers."""

import re

from pypdf import PdfReader

from jobagent.schemas.harness import ResumeHeader
from jobagent.schemas.optimizer import ResumeVariant

_BULLETS = "•▸▪·◦"
_INTERNAL_NOTE = re.compile(
    r"内部批注|内部备注|定制目标岗位|仅供内部|"
    r"\b(?:internal\s+(?:note|comment)|reviewer\s+(?:note|comment))\s*[:\uFF1A]|"
    r"\bproof_pending\b|(?m:^\s*TODO\s*:)",
    re.IGNORECASE,
)


def internal_note_issues(text: str) -> list[str]:
    return ["internal_annotation"] if _INTERNAL_NOTE.search(text) else []


def compare_variant_text(
    text: str,
    variant: ResumeVariant,
    header: ResumeHeader | None = None,
) -> list[str]:
    issues: list[str] = []
    if not variant.verification.passed or not variant.items or not variant.claim_ledger.claims:
        issues.append("variant_not_verified")
    remainder = "".join(text.split())
    if not remainder:
        issues.append("missing_text")
    if header is not None:
        supplied = "".join("".join(header.lines).split())
        if remainder.startswith(supplied):
            remainder = remainder[len(supplied) :]
        else:
            issues.append("header_missing_or_altered")
    for item in variant.items:
        heading = "".join(item.section.split())
        if remainder.startswith(heading):
            remainder = remainder[len(heading) :]
        if remainder[:1] and remainder[0] in _BULLETS:
            remainder = remainder[1:]
        expected = "".join(item.text.split())
        if remainder.startswith(expected):
            remainder = remainder[len(expected) :]
        else:
            issues.append("item_missing_or_reordered:" + item.id)
            break
    if remainder:
        issues.append("unapproved_or_extra_text")
    return issues


def pdf_review_issues(reader: PdfReader) -> list[str]:
    issues: list[str] = []
    root = reader.root_object
    names = root.get("/Names", {})
    if hasattr(names, "get_object"):
        names = names.get_object()
    if "/EmbeddedFiles" in names:
        issues.append("pdf_attachments")
    if any(key in root for key in ("/OpenAction", "/AA", "/AcroForm")) or "/JavaScript" in names:
        issues.append("pdf_active_content")
    for page in reader.pages:
        if "/AA" in page:
            issues.append("pdf_active_content")
        for reference in page.get("/Annots", []):
            annotation = reference.get_object()
            if annotation.get("/Subtype") != "/Link":
                issues.append("pdf_review_annotations")
            if "/AA" in annotation:
                issues.append("pdf_active_content")
            action = annotation.get("/A")
            if action is not None:
                action = action.get_object()
                if action.get("/S") not in {"/URI", "/GoTo"}:
                    issues.append("pdf_active_content")
                if str(action.get("/URI", "")).casefold().startswith(("javascript:", "data:")):
                    issues.append("pdf_active_content")
            issues.extend(internal_note_issues(str(annotation.get("/Contents", ""))))
    if reader.metadata is not None:
        issues.extend(internal_note_issues("\n".join(str(v) for v in reader.metadata.values())))
    metadata = root.get("/Metadata")
    if metadata is not None:
        issues.extend(
            internal_note_issues(metadata.get_object().get_data().decode("utf-8", errors="replace"))
        )
    return list(dict.fromkeys(issues))
