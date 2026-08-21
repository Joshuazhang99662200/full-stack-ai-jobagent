import hashlib
from pathlib import Path

import pytest
from pypdf import PdfWriter
from reportlab.pdfgen.canvas import Canvas

from jobagent.errors import ResumeParseError
from jobagent.parsing.pdf_resume import PdfResumeParser


def make_text_pdf(path: Path) -> None:
    canvas = Canvas(str(path))
    canvas.drawString(72, 720, "Ada Lovelace - Python Engineer")
    canvas.showPage()
    canvas.drawString(72, 720, "Built evidence-grounded workflow tooling")
    canvas.save()


def test_parser_extracts_ordered_pages_and_content_digest(tmp_path: Path) -> None:
    path = tmp_path / "resume.pdf"
    make_text_pdf(path)

    parsed = PdfResumeParser().parse(path, "CAND_001")

    expected_digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert parsed.id == f"RESUME_{expected_digest[:16].upper()}"
    assert parsed.content_digest == f"sha256:{expected_digest}"
    assert parsed.source_name == "resume.pdf"
    assert [page.page_number for page in parsed.pages] == [1, 2]
    assert "Ada Lovelace" in parsed.pages[0].text
    assert "evidence-grounded" in parsed.pages[1].text


def test_page_without_extractable_text_is_explicit(tmp_path: Path) -> None:
    path = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with path.open("wb") as output:
        writer.write(output)

    parsed = PdfResumeParser().parse(path, "CAND_001")

    assert parsed.pages[0].text == ""
    assert parsed.pages[0].warnings == ["NO_EXTRACTABLE_TEXT"]
    assert parsed.warnings == ["PAGES_WITHOUT_EXTRACTABLE_TEXT"]


def test_missing_resume_returns_typed_error(tmp_path: Path) -> None:
    with pytest.raises(ResumeParseError, match="does not exist") as captured:
        PdfResumeParser().parse(tmp_path / "missing.pdf", "CAND_001")

    assert captured.value.code == "RESUME_PARSE_ERROR"


def test_encrypted_resume_returns_typed_error(tmp_path: Path) -> None:
    path = tmp_path / "encrypted.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt("secret")
    with path.open("wb") as output:
        writer.write(output)

    with pytest.raises(ResumeParseError, match="encrypted"):
        PdfResumeParser().parse(path, "CAND_001")
