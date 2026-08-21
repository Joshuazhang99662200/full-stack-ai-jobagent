"""Candidate draft extraction through the structured reasoning port."""

import re
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from jobagent.capabilities import ReasoningProvider
from jobagent.errors import InvalidProviderOutputError
from jobagent.schemas.candidate import CandidateDraft, ParsedResume
from jobagent.schemas.common import SourceType

PROMPT_ID = "candidate.extract_draft.v1"


class ReasoningCandidateDraftExtractor:
    """Turn parsed resume text into an unconfirmed, source-bound candidate draft."""

    def __init__(self, provider: ReasoningProvider) -> None:
        self.provider = provider

    def extract(self, resume: ParsedResume) -> CandidateDraft:
        context: Mapping[str, Any] = {
            "resume_id": resume.id,
            "candidate_id": resume.candidate_id,
            "source_name": resume.source_name,
            "content_digest": resume.content_digest,
            "pages": [
                {"page_number": page.page_number, "text": page.text} for page in resume.pages
            ],
            "evidence_policy": {
                "facts_only": True,
                "user_confirmed": False,
                "source_reference_format": f"{resume.id}:page:<number>",
            },
        }
        raw_output = self.provider.generate(
            prompt_id=PROMPT_ID,
            context=context,
            output_type=CandidateDraft,
        )
        draft = self._revalidate(raw_output)
        self._validate_resume_binding(resume, draft)
        return draft

    @staticmethod
    def _revalidate(raw_output: CandidateDraft) -> CandidateDraft:
        try:
            return CandidateDraft.model_validate(raw_output.model_dump(mode="python"))
        except (AttributeError, TypeError, ValidationError) as error:
            raise InvalidProviderOutputError(
                "Candidate draft provider output violated the schema.",
                details={"prompt_id": PROMPT_ID},
            ) from error

    @staticmethod
    def _validate_resume_binding(resume: ParsedResume, draft: CandidateDraft) -> None:
        if draft.candidate_id != resume.candidate_id:
            raise InvalidProviderOutputError(
                "Candidate draft belongs to a different candidate.",
                details={"prompt_id": PROMPT_ID, "resume_id": resume.id},
            )

        valid_pages = {page.page_number for page in resume.pages}
        source_pattern = re.compile(rf"^{re.escape(resume.id)}:page:(\d+)$")
        for evidence in draft.evidence:
            match = source_pattern.fullmatch(evidence.source.reference)
            if (
                evidence.source.type is not SourceType.RESUME
                or match is None
                or int(match.group(1)) not in valid_pages
            ):
                raise InvalidProviderOutputError(
                    "Candidate draft evidence is not bound to the parsed resume.",
                    details={
                        "prompt_id": PROMPT_ID,
                        "resume_id": resume.id,
                        "evidence_id": evidence.id,
                    },
                )
