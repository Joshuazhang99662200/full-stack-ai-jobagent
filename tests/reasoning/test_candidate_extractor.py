from collections.abc import Mapping
from typing import Any

import pytest

from jobagent.errors import InvalidProviderOutputError
from jobagent.reasoning.candidate_extractor import ReasoningCandidateDraftExtractor
from jobagent.schemas.candidate import (
    CandidateDraft,
    CandidateProfile,
    Confidence,
    EvidenceItem,
    EvidenceType,
    ParsedResume,
    ResumePage,
)
from jobagent.schemas.common import ContractModel, SourceReference, SourceType


def parsed_resume() -> ParsedResume:
    return ParsedResume(
        id="RESUME_001",
        candidate_id="CAND_001",
        source_name="resume.pdf",
        content_digest="sha256:abc123",
        pages=[ResumePage(page_number=1, text="Built internal Python tooling.")],
    )


def draft_evidence(*, confirmed: bool = False, resume_id: str = "RESUME_001") -> EvidenceItem:
    return EvidenceItem(
        id="EVID_001",
        type=EvidenceType.EXPERIENCE,
        statement="Built internal Python tooling.",
        source=SourceReference(type=SourceType.RESUME, reference=f"{resume_id}:page:1"),
        confidence=Confidence.EXPLICIT,
        user_confirmed=confirmed,
    )


class FakeProvider:
    def __init__(self, output: CandidateDraft) -> None:
        self.output = output
        self.prompt_id: str | None = None
        self.context: Mapping[str, Any] | None = None
        self.output_type: type[ContractModel] | None = None

    def generate(
        self,
        *,
        prompt_id: str,
        context: Mapping[str, Any],
        output_type: type[ContractModel],
    ) -> Any:
        self.prompt_id = prompt_id
        self.context = context
        self.output_type = output_type
        return self.output


def test_extractor_uses_typed_prompt_and_minimum_resume_context() -> None:
    output = CandidateDraft(
        candidate_id="CAND_001",
        profile=CandidateProfile(id="CAND_001"),
        evidence=[draft_evidence()],
    )
    provider = FakeProvider(output)

    result = ReasoningCandidateDraftExtractor(provider).extract(parsed_resume())

    assert result == output
    assert provider.prompt_id == "candidate.extract_draft.v1"
    assert provider.output_type is CandidateDraft
    assert provider.context is not None
    assert provider.context["resume_id"] == "RESUME_001"
    assert provider.context["pages"] == [
        {"page_number": 1, "text": "Built internal Python tooling."}
    ]


@pytest.mark.parametrize("invalid_kind", ["candidate", "confirmed", "source"])
def test_extractor_rejects_untrusted_invalid_provider_output(invalid_kind: str) -> None:
    evidence = draft_evidence(
        confirmed=invalid_kind == "confirmed",
        resume_id="RESUME_OTHER" if invalid_kind == "source" else "RESUME_001",
    )
    candidate_id = "CAND_OTHER" if invalid_kind == "candidate" else "CAND_001"
    output = CandidateDraft.model_construct(
        candidate_id=candidate_id,
        profile=CandidateProfile(id="CAND_001"),
        evidence=[evidence],
    )

    with pytest.raises(InvalidProviderOutputError):
        ReasoningCandidateDraftExtractor(FakeProvider(output)).extract(parsed_resume())
