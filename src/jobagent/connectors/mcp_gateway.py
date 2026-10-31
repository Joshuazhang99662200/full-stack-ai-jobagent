"""Bounded read-only execution; upstream transport calls the dispatch checkpoint."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Literal

from pydantic import JsonValue, TypeAdapter

from jobagent.errors import JobAgentError, UserInterventionRequiredError
from jobagent.schemas.mcp_calls import McpCallReceipt, McpCallRequest, McpProviderResult
from jobagent.storage.mcp_repository import SqliteMcpRepository

McpRunner = Callable[[McpCallRequest, Callable[[], None]], McpProviderResult]


class McpReadGateway:
    def __init__(
        self,
        repository: SqliteMcpRepository,
        runner: McpRunner,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.runner = runner
        self.clock = clock or (lambda: datetime.now(UTC))

    def execute(self, request: McpCallRequest) -> McpCallReceipt:
        return self.execute_batch([request])[0]

    def execute_batch(self, requests: list[McpCallRequest]) -> list[McpCallReceipt]:
        run, previous = self.repository.open_batch(requests, now=self.clock())
        if previous is not None:
            return previous
        with ThreadPoolExecutor(max_workers=run.max_parallel) as executor:
            return list(executor.map(self._execute_admitted, requests))

    def _execute_admitted(self, request: McpCallRequest) -> McpCallReceipt:
        dispatched = False

        def checkpoint() -> None:
            nonlocal dispatched
            if dispatched:
                raise RuntimeError("Transport attempted a second dispatch for one MCP call.")
            self.repository.mark_dispatched(request.call_id, now=self.clock())
            dispatched = True

        try:
            result = self.runner(request, checkpoint)
            result = McpProviderResult.model_validate(result.model_dump(mode="json"))
            return self.repository.finish(request.call_id, result, now=self.clock())
        except Exception as error:
            # A pre-checkpoint startup failure consumed no actual call. Once the
            # checkpoint commits, a crash/write/response failure is conservatively
            # unknown; it is never an invitation to replay the external request.
            status: Literal["unknown", "failed", "gate"] = "unknown" if dispatched else "failed"
            if dispatched and isinstance(error, UserInterventionRequiredError):
                status = "gate"
            failed = McpProviderResult(
                status=status,
                error_code=error.code if isinstance(error, JobAgentError) else None,
                reason=error.message
                if isinstance(error, JobAgentError)
                else (f"{type(error).__name__}: upstream execution could not be verified."),
                failure_details=TypeAdapter(dict[str, JsonValue]).validate_python(error.details)
                if isinstance(error, JobAgentError)
                else {},
            )
            return self.repository.finish(request.call_id, failed, now=self.clock())
