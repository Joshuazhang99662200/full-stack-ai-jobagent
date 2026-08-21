"""PDF resume parsing with stable page provenance."""

import hashlib
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from jobagent.errors import ResumeParseError
from jobagent.schemas.candidate import ParsedResume, ResumePage


class PdfResumeParser:
    """Extract text from a PDF without interpreting candidate claims."""

    def parse(self, path: Path, candidate_id: str) -> ParsedResume:
        if not path.is_file():
            raise ResumeParseError(
                "Resume PDF does not exist.",
                details={"source_name": path.name, "operation": "parse_resume"},
            )

        try:
            content = path.read_bytes()
            reader = PdfReader(BytesIO(content), strict=False)
        except (OSError, PdfReadError) as error:
            raise ResumeParseError(
                "Resume PDF could not be read.",
                details={"source_name": path.name, "operation": "parse_resume"},
            ) from error

        if reader.is_encrypted:
            raise ResumeParseError(
                "Resume PDF is encrypted; provide an unencrypted local copy.",
                details={"source_name": path.name, "operation": "parse_resume"},
            )
        if not reader.pages:
            raise ResumeParseError(
                "Resume PDF has no pages.",
                details={"source_name": path.name, "operation": "parse_resume"},
            )

        pages: list[ResumePage] = []
        pages_without_text = False
        try:
            for page_number, page in enumerate(reader.pages, start=1):
                text = (page.extract_text() or "").strip()
                warnings: list[str] = []
                if not text:
                    warnings.append("NO_EXTRACTABLE_TEXT")
                    pages_without_text = True
                pages.append(ResumePage(page_number=page_number, text=text, warnings=warnings))
        except (KeyError, PdfReadError, TypeError, ValueError) as error:
            raise ResumeParseError(
                "Resume PDF text extraction failed.",
                details={"source_name": path.name, "operation": "extract_text"},
            ) from error

        digest = hashlib.sha256(content).hexdigest()
        warnings = ["PAGES_WITHOUT_EXTRACTABLE_TEXT"] if pages_without_text else []
        return ParsedResume(
            id=f"RESUME_{digest[:16].upper()}",
            candidate_id=candidate_id,
            source_name=path.name,
            content_digest=f"sha256:{digest}",
            pages=pages,
            warnings=warnings,
        )
