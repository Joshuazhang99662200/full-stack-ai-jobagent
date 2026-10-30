"""Text and emphasis edits against an immutable, owner-selected Word template."""

from typing import Annotated

from pydantic import Field, model_validator

from jobagent.schemas.common import ContractModel, NonEmptyString


class WordRun(ContractModel):
    text: NonEmptyString
    bold: bool = False


class RunTextEdit(ContractModel):
    run_index: Annotated[int, Field(ge=0)]
    expected_text: str
    text: str


class ParagraphEdit(ContractModel):
    paragraph_index: Annotated[int, Field(ge=0)]
    expected_text: NonEmptyString
    runs: list[WordRun] = Field(default_factory=list)
    run_edits: list[RunTextEdit] = Field(default_factory=list)

    @model_validator(mode="after")
    def one_edit_mode(self) -> "ParagraphEdit":
        if bool(self.runs) == bool(self.run_edits):
            raise ValueError("Choose replacement runs or exact source-run edits, exclusively.")
        indices = [r.run_index for r in self.run_edits]
        if len(indices) != len(set(indices)):
            raise ValueError("A source run may be edited only once.")
        return self


class TemplatePatch(ContractModel):
    template_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    edits: list[ParagraphEdit] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_paragraphs(self) -> "TemplatePatch":
        indices = [e.paragraph_index for e in self.edits]
        if len(indices) != len(set(indices)):
            raise ValueError("A paragraph may be patched only once.")
        return self
