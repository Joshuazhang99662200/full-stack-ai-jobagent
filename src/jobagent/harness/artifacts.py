"""Read-only final-file inspection and content binding before employer delivery."""

import hashlib
import io
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from jobagent.errors import ContractValidationError
from jobagent.harness.artifact_rules import (
    compare_variant_text,
    internal_note_issues,
    pdf_review_issues,
)
from jobagent.schemas.artifacts import ArtifactCheckReport, ArtifactMediaType, EmployerArtifact
from jobagent.schemas.harness import ResumeHeader
from jobagent.schemas.optimizer import ResumeVariant

_PDF: ArtifactMediaType = "application/pdf"
_WORD: ArtifactMediaType = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_MAX_UNCOMPRESSED = 64 * 1024 * 1024


def _word_text_and_issues(content: bytes) -> tuple[str, list[str]]:
    issues: list[str] = []
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        entries = archive.infolist()
        names = archive.namelist()
        if (
            len(names) != len(set(names))
            or sum(item.file_size for item in entries) > _MAX_UNCOMPRESSED
        ):
            return "", ["word_invalid_container"]
        if any(name.startswith("word/comments") for name in names):
            issues.append("word_comments")
        if any(
            name.startswith("word/embeddings/") or name.endswith("vbaProject.bin") for name in names
        ):
            issues.append("word_embedded_payload")
        if "docProps/custom.xml" in names:
            issues.append("word_custom_properties")
        text_by_part: dict[str, str] = {}
        for name in names:
            if not name.endswith(".xml") or not name.startswith(("word/", "docProps/")):
                continue
            root = ElementTree.fromstring(archive.read(name))
            tags = {node.tag for node in root.iter()}
            if tags & {_WORD_NS + item for item in ("ins", "del", "moveFrom", "moveTo")}:
                issues.append("word_revisions")
            if any(
                node.tag in {_WORD_NS + "vanish", _WORD_NS + "webHidden"}
                and node.get(_WORD_NS + "val", "true").casefold() not in {"0", "false", "off"}
                for node in root.iter()
            ):
                issues.append("word_hidden_content")
            if tags & {
                _WORD_NS + item
                for item in ("commentReference", "commentRangeStart", "commentRangeEnd")
            }:
                issues.append("word_comments")
            all_text = "\n".join(node.text or "" for node in root.iter())
            issues.extend(internal_note_issues(all_text))
            if name == "word/document.xml" or name.startswith(("word/header", "word/footer")):
                text_by_part[name] = "".join(node.text or "" for node in root.iter(_WORD_NS + "t"))
        if "word/document.xml" not in text_by_part:
            issues.append("word_missing_document")
        ordered = [name for name in sorted(text_by_part) if name.startswith("word/header")]
        ordered += ["word/document.xml"]
        ordered += [name for name in sorted(text_by_part) if name.startswith("word/footer")]
        return "\n".join(text_by_part.get(name, "") for name in ordered), issues


def check_artifact(
    path: Path,
    *,
    variant: ResumeVariant | None = None,
    header: ResumeHeader | None = None,
) -> ArtifactCheckReport:
    """Inspect actual bytes without rewriting. Issue codes never disclose document text."""
    content = b""
    media_type: ArtifactMediaType | None = None
    issues: list[str] = []
    try:
        content = path.read_bytes()
        if path.suffix.casefold() == ".pdf":
            media_type = _PDF
            reader = PdfReader(io.BytesIO(content), strict=True)
            issues.extend(pdf_review_issues(reader))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        elif path.suffix.casefold() == ".docx":
            media_type = _WORD
            text, word_issues = _word_text_and_issues(content)
            issues.extend(word_issues)
        else:
            text = ""
            issues.append("unsupported_artifact_type")
        issues.extend(internal_note_issues(text))
        if variant is not None:
            issues.extend(compare_variant_text(text, variant, header))
    except (
        OSError,
        ValueError,
        PdfReadError,
        KeyError,
        TypeError,
        zipfile.BadZipFile,
        ElementTree.ParseError,
    ):
        issues.append("unreadable_artifact")
    return ArtifactCheckReport(
        digest="sha256:" + hashlib.sha256(content).hexdigest(),
        media_type=media_type,
        passed=not issues,
        issues=list(dict.fromkeys(issues)),
    )


def bind_artifact(
    path: Path,
    variant: ResumeVariant,
    header: ResumeHeader | None = None,
) -> EmployerArtifact:
    report = check_artifact(path, variant=variant, header=header)
    if not report.passed or report.media_type is None:
        raise ContractValidationError(
            "Final employer artifact failed checks.", details={"issues": report.issues}
        )
    return EmployerArtifact(
        path=str(path.resolve()),
        digest=report.digest,
        media_type=report.media_type,
        header_lines=[] if header is None else header.lines,
    )


def verify_artifact(binding: EmployerArtifact, variant: ResumeVariant) -> None:
    header = ResumeHeader(lines=binding.header_lines) if binding.header_lines else None
    report = check_artifact(Path(binding.path), variant=variant, header=header)
    if report.digest != binding.digest or report.media_type != binding.media_type:
        raise ContractValidationError(
            "Final employer artifact changed; review and approve it again."
        )
    if not report.passed:
        raise ContractValidationError(
            "Final employer artifact failed checks.", details={"issues": report.issues}
        )
