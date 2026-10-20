from datetime import UTC, datetime

from reportlab.pdfgen import canvas

from jobagent.harness.pdf import check_pdf
from jobagent.schemas.harness import ResumeHeader
from jobagent.schemas.optimizer import ResumeDiff, ResumeVariant, VerificationReport
from tests.optimizer.test_review import draft


def variant():
    document = draft()
    return ResumeVariant(
        id="RESUME_1",
        target_job_id="JOB_1",
        target_role="Engineer",
        items=document.items,
        claim_ledger=document.claim_ledger,
        keyword_coverage=document.keyword_coverage,
        verification=VerificationReport(passed=True, evidence_coverage=1),
        diff=ResumeDiff(),
        prompt_bundle_digest="sha256:test",
        generated_at=datetime.now(UTC),
    )


def render(path, text, *, pages=1):
    pdf = canvas.Canvas(str(path))
    pdf.drawString(50, 700, text)
    for _ in range(pages - 1):
        pdf.showPage()
        pdf.drawString(50, 700, "extra page")
    pdf.save()


def test_pdf_requires_all_approved_text_and_rejects_extra_claims(tmp_path):
    path = tmp_path / "resume.pdf"
    document = variant()
    render(path, document.items[0].text)
    assert check_pdf(document, path).passed
    render(path, "Managed 900 engineers.")
    assert not check_pdf(document, path).passed
    render(path, document.items[0].text + " Invented new growth.")
    assert not check_pdf(document, path).passed


def test_pdf_limits_pages_and_refuses_unverified_variant(tmp_path):
    path = tmp_path / "resume.pdf"
    document = variant()
    render(path, document.items[0].text, pages=3)
    assert "page_limit" in check_pdf(document, path, max_pages=2).issues
    document.verification = VerificationReport(passed=False, evidence_coverage=0)
    assert "variant_not_verified" in check_pdf(document, path).issues


def test_pdf_rejects_reordered_text_and_unreadable_file(tmp_path):
    path = tmp_path / "resume.pdf"
    document = variant()
    document.items.append(
        document.items[0].model_copy(update={"id": "ITEM_2", "text": "Built a Python service."})
    )
    render(path, document.items[1].text + " " + document.items[0].text)
    assert not check_pdf(document, path).passed
    path.write_bytes(b"invalid PDF")
    assert "unreadable_pdf" in check_pdf(document, path).issues


def render_lines(path, lines):
    pdf = canvas.Canvas(str(path))
    y = 760
    for line in lines:
        pdf.drawString(50, y, line)
        y -= 20
    pdf.save()


def test_pdf_header_lines_are_allowed_only_verbatim_at_the_top(tmp_path):
    path = tmp_path / "resume.pdf"
    document = variant()
    header = ResumeHeader(lines=["Ada Lovelace", "ada@example.com | Engineer"])
    body = document.items[0].text

    render_lines(path, [*header.lines, body])
    report = check_pdf(document, path, header=header)
    assert report.passed
    assert report.header_digest is not None and report.header_digest.startswith("sha256:")

    assert "unapproved_or_extra_text" in check_pdf(document, path).issues
    render_lines(path, [body, *header.lines])
    assert not check_pdf(document, path, header=header).passed
    render_lines(path, ["Ada Lovelace", "ada@example.com | Staff Engineer", body])
    assert not check_pdf(document, path, header=header).passed


def test_pdf_allows_bullet_glyphs_but_no_other_decoration(tmp_path):
    path = tmp_path / "resume.pdf"
    document = variant()
    render(path, "· " + document.items[0].text)
    assert check_pdf(document, path).passed
    render(path, "NEW " + document.items[0].text)
    assert not check_pdf(document, path).passed
