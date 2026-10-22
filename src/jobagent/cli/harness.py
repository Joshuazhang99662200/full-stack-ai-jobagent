"""CLI for portable progress and artifact checkpoints."""

import json
from pathlib import Path
from typing import Annotated, Never

import typer
from pydantic import ValidationError

from jobagent.errors import ContractValidationError, JobAgentError
from jobagent.harness.pdf import check_pdf
from jobagent.harness.reporting import build_report
from jobagent.harness.service import HarnessService
from jobagent.schemas.applications import ApplicationPackage
from jobagent.schemas.harness import Host, ResumeHeader, RunPhase
from jobagent.schemas.optimizer import ResumeVariant
from jobagent.storage.application_repository import SqliteApplicationAuditRepository
from jobagent.storage.database import Database

harness_app = typer.Typer(help="Portable workflow state; no approval or delivery actions.")
Workspace = Annotated[Path, typer.Option("--workspace")]
Session = Annotated[str, typer.Option("--session-id")]


def _fail(error: JobAgentError | ValidationError) -> Never:
    message = error.message if isinstance(error, JobAgentError) else "Invalid run contract."
    typer.echo(json.dumps({"error": {"message": message}}))
    raise typer.Exit(1)


@harness_app.command("start")
def start(
    candidate_id: str, host: Host, session_id: Session, workspace: Workspace = Path(".")
) -> None:
    try:
        typer.echo(
            HarnessService(workspace).start(candidate_id, host, session_id).model_dump_json()
        )
    except (JobAgentError, ValidationError) as error:
        _fail(error)


@harness_app.command("status")
def status(run_id: str, workspace: Workspace = Path(".")) -> None:
    try:
        typer.echo(HarnessService(workspace).status(run_id).model_dump_json(indent=2))
    except JobAgentError as error:
        _fail(error)


@harness_app.command("resume")
def resume(
    run_id: str,
    host: Host,
    session_id: Session,
    workspace: Workspace = Path("."),
    recover: Annotated[bool, typer.Option("--recover")] = False,
) -> None:
    try:
        typer.echo(
            HarnessService(workspace)
            .resume(
                run_id,
                host,
                session_id,
                recover=recover,
            )
            .model_dump_json()
        )
    except (JobAgentError, ValidationError) as error:
        _fail(error)


@harness_app.command("checkpoint")
def checkpoint(
    run_id: str,
    phase: RunPhase,
    session_id: Session,
    workspace: Workspace = Path("."),
    artifact: Annotated[Path | None, typer.Option("--artifact")] = None,
    contract: Annotated[str | None, typer.Option("--contract")] = None,
) -> None:
    try:
        typer.echo(
            HarnessService(workspace)
            .checkpoint(
                run_id,
                session_id,
                phase,
                artifact,
                contract,
            )
            .model_dump_json()
        )
    except (JobAgentError, ValidationError) as error:
        _fail(error)


@harness_app.command("release")
def release(run_id: str, session_id: Session, workspace: Workspace = Path(".")) -> None:
    try:
        typer.echo(HarnessService(workspace).release(run_id, session_id).model_dump_json())
    except JobAgentError as error:
        _fail(error)


@harness_app.command("check-pdf")
def check_pdf_command(
    variant_path: Path,
    pdf_path: Path,
    max_pages: Annotated[int, typer.Option("--max-pages", min=1)] = 2,
    header_path: Annotated[
        Path | None,
        typer.Option("--header", help="JSON {lines: [...]} allowed verbatim above the items."),
    ] = None,
) -> None:
    try:
        variant = ResumeVariant.model_validate_json(variant_path.read_bytes())
        header = (
            None
            if header_path is None
            else ResumeHeader.model_validate_json(header_path.read_bytes())
        )
        report = check_pdf(variant, pdf_path, max_pages=max_pages, header=header)
        typer.echo(report.model_dump_json(indent=2))
        if not report.passed:
            raise typer.Exit(1)
    except (JobAgentError, ValidationError) as error:
        _fail(error)
    except OSError:
        typer.echo(json.dumps({"error": {"message": "Variant file unavailable."}}))
        raise typer.Exit(1) from None


@harness_app.command("report")
def report(
    run_id: str,
    workspace: Workspace = Path("."),
    database: Annotated[Path, typer.Option("--database")] = Path(".jobagent/jobagent.sqlite3"),
) -> None:
    try:
        service = HarnessService(workspace)
        run = service.status(run_id)
        packages = []
        for artifact in run.artifacts:
            if artifact.contract == "ApplicationPackage":
                path = service.workspace / artifact.path
                if service._artifact(path, artifact.contract) != artifact:
                    raise ValueError("Saved application artifact changed")
                packages.append(ApplicationPackage.model_validate_json(path.read_bytes()))
        path = database if database.is_absolute() else service.workspace / database
        audits = (
            SqliteApplicationAuditRepository(Database(path)).list_audits() if path.exists() else []
        )
        typer.echo(build_report(run_id, packages, audits).model_dump_json(indent=2))
    except (JobAgentError, ValidationError) as error:
        _fail(error)
    except (OSError, ValueError):
        typer.echo(
            json.dumps({"error": {"message": "Saved application artifact changed or unavailable."}})
        )
        raise typer.Exit(1) from None


@harness_app.command("render")
def render(
    variant_path: Annotated[Path, typer.Argument(help="Verified ResumeVariant JSON.")],
    header_path: Annotated[Path, typer.Argument(help='ResumeHeader JSON: {"lines": [...]}.')],
    pdf: Annotated[Path | None, typer.Option("--pdf", help="Where to write the PDF.")] = None,
    docx: Annotated[
        Path | None, typer.Option("--docx", help="Where to write the Word file.")
    ] = None,
    font: Annotated[
        str | None,
        typer.Option("--font", help="A TTF/TTC path; 'none' for Helvetica; default: a CJK font."),
    ] = None,
    bold_font: Annotated[str | None, typer.Option("--bold-font")] = None,
    word_font: Annotated[str, typer.Option("--word-font")] = "DengXian",
    summary_section: Annotated[
        list[str] | None, typer.Option("--summary-section", help="Sections set as paragraphs.")
    ] = None,
    max_pages: Annotated[int, typer.Option("--max-pages", min=1)] = 1,
) -> None:
    """Lay out a verified variant as PDF and/or Word, then run the PDF text gate.

    Layout only: every visible line is a header line or verbatim item text. A Word
    file cannot be checked directly; export it to PDF and run `harness check-pdf`.
    """
    from jobagent.rendering.resume import (
        DEFAULT_SUMMARY_SECTIONS,
        default_cjk_font,
        render_docx,
        render_pdf,
    )
    try:
        if pdf is None and docx is None:
            raise ContractValidationError("Choose at least one output: --pdf or --docx.")
        try:
            variant = ResumeVariant.model_validate_json(variant_path.read_bytes())
            header = ResumeHeader.model_validate_json(header_path.read_bytes())
        except (OSError, ValidationError):
            raise ContractValidationError(
                "The variant or header file could not be read.",
                details={"variant": variant_path.name, "header": header_path.name},
            ) from None
        sections = set(summary_section) if summary_section else DEFAULT_SUMMARY_SECTIONS
        result: dict[str, object] = {"variant_id": variant.id}
        if pdf is not None:
            regular, bold = font, bold_font
            if font is None:
                found = default_cjk_font()
                if found is None:
                    raise ContractValidationError(
                        "No CJK font was found; pass --font with a TTF/TTC path."
                    )
                regular, bold = found
            elif font.lower() == "none":
                regular, bold = None, None
            render_pdf(
                variant,
                header,
                pdf,
                font_path=regular,
                bold_font_path=bold,
                summary_sections=sections,
            )
            report = check_pdf(variant, pdf, max_pages=max_pages, header=header)
            result.update({"pdf": str(pdf), "check": report.model_dump(mode="json")})
        if docx is not None:
            render_docx(variant, header, docx, font_name=word_font, summary_sections=sections)
            result["docx"] = str(docx)
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
        check = result.get("check")
        if isinstance(check, dict) and not check.get("passed"):
            raise typer.Exit(code=1)
    except JobAgentError as error:
        _fail(error)
