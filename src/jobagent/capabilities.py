"""Provider-neutral ports for atomic JobAgent capabilities."""

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, TypeVar, runtime_checkable

from jobagent.schemas.applications import ApplicationPackage, DeliveryRequest, DeliveryResult
from jobagent.schemas.common import ContractModel
from jobagent.schemas.coordinator import CodexTextRequest
from jobagent.schemas.jobs import NormalizedJob, RecruiterInfo

InputT_contra = TypeVar("InputT_contra", bound=ContractModel, contravariant=True)
OutputT_co = TypeVar("OutputT_co", bound=ContractModel, covariant=True)
ReasoningOutputT = TypeVar("ReasoningOutputT", bound=ContractModel)


@runtime_checkable
class Capability(Protocol[InputT_contra, OutputT_co]):
    """One typed capability with no implied neighboring operations."""

    name: str

    def __call__(self, data: InputT_contra) -> OutputT_co: ...


@runtime_checkable
class JobSource(Protocol):
    """Stable boundary implemented by platform-specific connectors."""

    def search(self, *, query: Mapping[str, Any]) -> Sequence[NormalizedJob]: ...

    def fetch_job(self, source_job_id: str) -> NormalizedJob: ...

    def get_recruiter(self, source_job_id: str) -> RecruiterInfo | None: ...

    def preview_application(self, package: ApplicationPackage) -> ApplicationPackage: ...

    def submit_application(self, request: DeliveryRequest) -> DeliveryResult: ...


@runtime_checkable
class ReasoningProvider(Protocol):
    """Structured reasoning boundary with no vendor-specific model type."""

    def generate(
        self,
        *,
        prompt_id: str,
        context: Mapping[str, Any],
        output_type: type[ReasoningOutputT],
    ) -> ReasoningOutputT: ...


ModelT = TypeVar("ModelT", bound=ContractModel)


class TextRunner(Protocol):
    """A bounded, text-only model invocation: one task in, one validated contract out.

    Implemented by the local Codex and Gemini CLI runners; providers never see which.
    """

    def run(self, request: CodexTextRequest, output_contract: type[ModelT]) -> ModelT: ...
