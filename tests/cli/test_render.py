from pathlib import Path

import pytest

from jobagent.schemas.optimizer import VerificationReport
from tests.cli.test_outreach import invoke
from tests.rendering.test_resume import HEADER, resume_variant

pytest.importorskip("docx")


def files(tmp_path: Path, document) -> tuple[Path, Path]:  # type: ignore[no-untyped-def]
    variant_path = tmp_path / "variant.json"
    variant_path.write_text(document.model_dump_json(), encoding="utf-8")
    header_path = tmp_path / "header.json"
    header_path.write_text(HEADER.model_dump_json(), encoding="utf-8")
    return variant_path, header_path


def test_render_writes_both_files_and_checks_the_pdf(tmp_path: Path) -> None:
    variant_path, header_path = files(tmp_path, resume_variant())
    pdf, word = tmp_path / "out.pdf", tmp_path / "out.docx"

    code, report = invoke(
        "harness",
        "render",
        str(variant_path),
        str(header_path),
        "--pdf",
        str(pdf),
        "--docx",
        str(word),
        "--font",
        "none",
        "--summary-section",
        "Summary",
        "--max-pages",
        "1",
    )

    assert code == 0, report
    assert isinstance(report, dict) and report["check"]["passed"] is True
    assert pdf.is_file() and word.is_file()


def test_render_refuses_an_unverified_variant(tmp_path: Path) -> None:
    unverified = resume_variant().model_copy(
        update={"verification": VerificationReport(passed=False, evidence_coverage=0)}
    )
    variant_path, header_path = files(tmp_path, unverified)

    code, report = invoke(
        "harness",
        "render",
        str(variant_path),
        str(header_path),
        "--pdf",
        str(tmp_path / "x.pdf"),
        "--font",
        "none",
    )

    assert code == 1 and isinstance(report, dict)
    assert not (tmp_path / "x.pdf").exists()
