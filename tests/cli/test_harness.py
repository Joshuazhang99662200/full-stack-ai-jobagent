import json

from typer.testing import CliRunner

from jobagent.cli.app import app


def test_cli_start_status_release_and_handoff(tmp_path):
    runner = CliRunner()
    arguments = ["--workspace", str(tmp_path)]
    start = runner.invoke(
        app, ["harness", "start", "CAND_001", "codex", "--session-id", "a", *arguments]
    )
    assert start.exit_code == 0, start.output
    run_id = json.loads(start.output)["run_id"]
    assert runner.invoke(app, ["harness", "status", run_id, *arguments]).exit_code == 0
    assert (
        runner.invoke(
            app, ["harness", "release", run_id, "--session-id", "a", *arguments]
        ).exit_code
        == 0
    )
    result = runner.invoke(
        app, ["harness", "resume", run_id, "claude-code", "--session-id", "b", *arguments]
    )
    assert result.exit_code == 0
    assert json.loads(result.output)["host"] == "claude-code"


def test_cli_invalid_host_and_identifier_do_not_create_state(tmp_path):
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["harness", "start", "CAND_001", "bad", "--session-id", "a", "--workspace", str(tmp_path)],
    )
    assert result.exit_code != 0
    assert not (tmp_path / ".jobagent").exists()


def test_cli_check_pdf_accepts_a_verbatim_header_file(tmp_path):
    from reportlab.pdfgen import canvas

    from tests.harness.test_pdf import variant

    runner = CliRunner()
    document = variant()
    variant_path = tmp_path / "variant.json"
    variant_path.write_text(document.model_dump_json(), encoding="utf-8")
    header_path = tmp_path / "header.json"
    header_path.write_text(json.dumps({"lines": ["Ada Lovelace", "ada@example.com"]}), "utf-8")
    pdf_path = tmp_path / "resume.pdf"
    pdf = canvas.Canvas(str(pdf_path))
    for y, line in ((760, "Ada Lovelace"), (740, "ada@example.com"), (720, document.items[0].text)):
        pdf.drawString(50, y, line)
    pdf.save()

    without = runner.invoke(app, ["harness", "check-pdf", str(variant_path), str(pdf_path)])
    with_header = runner.invoke(
        app,
        ["harness", "check-pdf", str(variant_path), str(pdf_path), "--header", str(header_path)],
    )

    assert without.exit_code != 0
    assert with_header.exit_code == 0, with_header.output
    assert json.loads(with_header.output)["header_digest"].startswith("sha256:")
