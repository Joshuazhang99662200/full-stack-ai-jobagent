"""Explicit private configuration for the supported read-only stdio transport."""

from pydantic import Field, field_validator, model_validator

from jobagent.schemas.common import ContractModel, NonEmptyString

SEARCH_TOOLS = frozenset({"search_jobs", "search_job", "job_search"})
VIEW_TOOLS = frozenset({"get_job_detail", "job_detail", "view_job", "get_job"})


class McpStdioConfig(ContractModel):
    command: list[NonEmptyString] = Field(min_length=1, max_length=32, repr=False)
    search_tool: NonEmptyString
    view_tool: NonEmptyString
    timeout_seconds: float = Field(default=30, gt=0, le=120)
    max_response_bytes: int = Field(default=2_097_152, ge=1024, le=16_777_216)

    @field_validator("command")
    @classmethod
    def literal_argv(cls, value: list[str]) -> list[str]:
        if any("\x00" in part or not part.strip() for part in value):
            raise ValueError("Upstream argv must contain nonempty literal arguments.")
        return value

    @model_validator(mode="after")
    def readonly_mapping(self) -> "McpStdioConfig":
        if self.search_tool not in SEARCH_TOOLS or self.view_tool not in VIEW_TOOLS:
            raise ValueError("Only supported search/view tool names can enter the read-only route.")
        return self
