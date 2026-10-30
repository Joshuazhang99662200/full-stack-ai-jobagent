"""Text-only inputs for the local Codex planning and drafting boundary."""

from typing import Annotated, Literal

from pydantic import Field, field_validator

from jobagent.schemas.common import ContractModel, NonEmptyString

CodexRequestId = Annotated[str, Field(pattern=r"^CTX_[A-Z0-9_]{1,80}$")]


def _text_only(value: str) -> str:
    if "data:image/" in value.lower():
        raise ValueError("Image data is not accepted by the text-only coordinator.")
    return value


class CodexTextRecord(ContractModel):
    record_id: NonEmptyString
    kind: Literal["jd", "evidence", "user_feedback", "execution_result", "search_policy"]
    text: Annotated[str, Field(min_length=1, max_length=60000)]

    _no_images = field_validator("text")(_text_only)


class CodexTextRequest(ContractModel):
    request_id: CodexRequestId
    instruction: Annotated[str, Field(min_length=1, max_length=10000)]
    records: list[CodexTextRecord] = Field(min_length=1, max_length=50)

    _no_images = field_validator("instruction")(_text_only)


class CodexTextReply(ContractModel):
    """A proposal only; this carries no human approval or execution authority."""

    request_id: CodexRequestId
    text: Annotated[str, Field(min_length=1, max_length=100000)]
