"""Bounded read-only MCP stdio client; business dispatch is explicitly accounted.

The upstream process and mapping are private operator configuration. Server
instructions and tool output remain data and cannot choose another operation.
"""

import json
import queue
import subprocess
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from jobagent.connectors.cli_source import CliListingSource
from jobagent.errors import (
    ContractValidationError,
    InvalidProviderOutputError,
    UserInterventionRequiredError,
)
from jobagent.schemas.mcp_calls import McpCallRequest, McpProviderResult
from jobagent.schemas.mcp_transport import McpStdioConfig
from jobagent.sources import SourceRegistry

PROTOCOL_VERSION = "2025-06-18"


class _ProtocolError(Exception):
    pass


class _RpcError(_ProtocolError):
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        super().__init__("Upstream returned a structured JSON-RPC error.")


class _Session:
    def __init__(self, config: McpStdioConfig) -> None:
        self.config = config
        self.process = subprocess.Popen(
            config.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.incoming: queue.Queue[bytes | Exception | None] = queue.Queue(maxsize=128)
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        self.sequence = 0

    def _read(self) -> None:
        stream = self.process.stdout
        assert stream is not None
        try:
            while True:
                line = stream.readline(self.config.max_response_bytes + 1)
                if not line:
                    self.incoming.put(None)
                    return
                if len(line) > self.config.max_response_bytes:
                    self.incoming.put(_ProtocolError("Upstream response exceeds its byte limit."))
                    return
                self.incoming.put(line)
        except (OSError, ValueError):
            self.incoming.put(_ProtocolError("Upstream response stream became unavailable."))

    def send(self, body: dict[str, Any]) -> None:
        stream = self.process.stdin
        assert stream is not None
        stream.write(json.dumps(body, ensure_ascii=False).encode("utf-8") + b"\n")
        stream.flush()

    def request(
        self, method: str, params: dict[str, Any], *, before_send: Callable[[], None] | None = None
    ) -> dict[str, Any]:
        self.sequence += 1
        rid = self.sequence
        if before_send is not None:
            before_send()
        self.send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        deadline = time.monotonic() + self.config.timeout_seconds
        for _ in range(128):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _ProtocolError("Upstream response timed out.")
            try:
                raw = self.incoming.get(timeout=remaining)
            except queue.Empty as error:
                raise _ProtocolError("Upstream response timed out.") from error
            if raw is None or isinstance(raw, Exception):
                raise _ProtocolError("Upstream response is missing or unavailable.")
            try:
                message = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as error:
                raise _ProtocolError("Upstream response is not UTF-8 JSON.") from error
            if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                raise _ProtocolError("Upstream response is not a JSON-RPC message.")
            if "id" not in message and isinstance(message.get("method"), str):
                continue
            if message.get("method") == "ping" and "id" in message:
                self.send({"jsonrpc": "2.0", "id": message["id"], "result": {}})
                continue
            if message.get("id") != rid or "method" in message:
                raise _ProtocolError("Unsolicited upstream request or mismatched response.")
            if "error" in message:
                if isinstance(message["error"], dict):
                    raise _RpcError(message["error"])
                raise _ProtocolError("Upstream returned a JSON-RPC error.")
            result = message.get("result")
            if not isinstance(result, dict):
                raise _ProtocolError("Upstream result must be a structured mapping.")
            return result
        raise _ProtocolError("Too many upstream notifications without a response.")

    def initialize(self, tool: str) -> None:
        result = self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "jobagent-readonly", "version": "1.0"},
            },
        )
        capabilities = result.get("capabilities")
        if (
            result.get("protocolVersion") != PROTOCOL_VERSION
            or not isinstance(capabilities, dict)
            or "tools" not in capabilities
        ):
            raise _ProtocolError("Upstream protocol or tool capability is incompatible.")
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        cursor: str | None = None
        seen: set[str] = set()
        for _ in range(16):
            page = self.request("tools/list", {"cursor": cursor} if cursor else {})
            tools = page.get("tools")
            if not isinstance(tools, list):
                raise _ProtocolError("Upstream tools list is unavailable.")
            for item in tools:
                if not isinstance(item, dict) or item.get("name") != tool:
                    continue
                annotations = item.get("annotations")
                if (
                    not isinstance(annotations, dict)
                    or annotations.get("readOnlyHint") is not True
                    or annotations.get("destructiveHint") is True
                ):
                    raise _ProtocolError("Upstream tool is not explicitly read-only.")
                return
            next_cursor = page.get("nextCursor")
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen:
                break
            seen.add(next_cursor)
            cursor = next_cursor
        raise _ProtocolError("Configured read-only tool is not available upstream.")

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=2)
        self.reader.join(timeout=0.2)
        if self.process.stdin is not None:
            self.process.stdin.close()
        if self.process.stdout is not None:
            self.process.stdout.close()


def _payload(result: dict[str, Any], *, search: bool) -> Any:
    if "structuredContent" in result:
        return result["structuredContent"]
    content = result.get("content")
    if not isinstance(content, list):
        raise InvalidProviderOutputError("MCP result has no structured content.")
    texts = [
        item["text"]
        for item in content
        if isinstance(item, dict)
        and item.get("type") == "text"
        and isinstance(item.get("text"), str)
    ]
    if len(texts) == 1:
        try:
            return json.loads(texts[0])
        except ValueError:
            if not search or result.get("isError") is True:
                return texts[0]
    raise InvalidProviderOutputError("MCP search needs one recognized structured response.")


def _business_failure(result: dict[str, Any], payload: Any) -> McpProviderResult | None:
    contexts: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        contexts.append(payload)
        for context in contexts:
            for key in ("error", "data", "result"):
                if isinstance(context.get(key), dict):
                    contexts.append(context[key])
                    if len(contexts) > 64:
                        return McpProviderResult(
                            status="failed", reason="upstream_envelope_nesting_limit"
                        )
    codes = [
        str(item[key])
        for item in contexts
        for key in ("code", "errorCode", "error_code")
        if item.get(key) is not None
    ]
    bad_codes = [code for code in codes if code.casefold() not in {"0", "200", "ok", "success"}]
    statuses = {str(item.get("status", "")).casefold() for item in contexts}
    failed = (
        result.get("isError") is True
        or bool(bad_codes)
        or bool(statuses & {"error", "failed", "failure", "blocked", "already_applied"})
        or any(item.get("success") is False or bool(item.get("error")) for item in contexts)
    )
    if not failed:
        return None
    message = " ".join(
        str(item.get(key, ""))
        for item in contexts
        for key in ("message", "msg", "error_description")
    )
    if isinstance(payload, str):
        message += " " + payload
    lowered = message.casefold()
    code = bad_codes[0] if bad_codes else None
    if "already_applied" in statuses or any(word in lowered for word in ("已投递", "已申请")):
        return McpProviderResult(
            status="already_applied",
            payload=payload,
            error_code=code,
            reason="source_already_applied",
        )
    if "blocked" in statuses or any(word in lowered for word in ("屏蔽", "blocked")):
        return McpProviderResult(
            status="blocked", payload=payload, error_code=code, reason="source_blocked"
        )
    if set(codes) & {"429001", "429", "401", "403"} or any(
        word in lowered
        for word in (
            "429001",
            "rate limit",
            "too many",
            "captcha",
            "token",
            "unauthorized",
            "登录",
            "验证码",
            "风控",
            "频繁",
        )
    ):
        return McpProviderResult(
            status="gate",
            payload=payload,
            error_code="429001" if "429001" in codes or "429001" in lowered else code,
            reason="source_intervention_required",
        )
    return McpProviderResult(
        status="failed", payload=payload, error_code=code, reason="upstream_business_failure"
    )


class StdioMcpRunner:
    def __init__(self, config: McpStdioConfig, *, source: str) -> None:
        self.config = config
        self.source = source

    def __call__(
        self, request: McpCallRequest, mark_dispatched: Callable[[], None]
    ) -> McpProviderResult:
        session: _Session | None = None
        dispatched = False

        def dispatch() -> None:
            nonlocal dispatched
            mark_dispatched()
            dispatched = True

        try:
            request = McpCallRequest.model_validate(request.model_dump(mode="json"))
            keys = (
                ("query", "keyword", "jobName", "job_name", "title")
                if request.operation == "search"
                else ("jobId", "job_id", "id", "source_job_id")
            )
            expected = (
                request.search_term if request.operation == "search" else request.source_job_id
            )
            targets = [str(request.arguments[key]) for key in keys if key in request.arguments]
            if not targets or any(target != expected for target in targets):
                return McpProviderResult(status="failed", reason="actual_target_mismatch")
            parser = CliListingSource(SourceRegistry.default().get(self.source))
            tool = (
                self.config.search_tool if request.operation == "search" else self.config.view_tool
            )
            session = _Session(self.config)
            session.initialize(tool)
            result = session.request(
                "tools/call", {"name": tool, "arguments": request.arguments}, before_send=dispatch
            )
            payload = _payload(result, search=request.operation == "search")
            failure = _business_failure(result, payload)
            if failure is not None:
                return failure
            if request.operation == "search":
                listings = parser.parse_listings(payload, collected_at=datetime.now(UTC))
                return McpProviderResult(
                    status="success", payload=payload, listings=listings, loaded=True
                )
            return McpProviderResult(status="success", payload=payload)
        except _RpcError as error:
            return _business_failure({"isError": True}, error.payload) or McpProviderResult(
                status="failed",
                reason="upstream_rpc_failure",
            )
        except ContractValidationError as error:
            return McpProviderResult(
                status="failed",
                error_code=error.code,
                reason=error.message,
                failure_details=error.details,
            )
        except UserInterventionRequiredError:
            return McpProviderResult(status="gate", reason="source_intervention_required")
        except InvalidProviderOutputError:
            return McpProviderResult(status="failed", reason="unrecognized_upstream_observation")
        except Exception:
            # Neither argv nor upstream exception text may leak credentials. A
            # dispatch without a usable result remains uncertain, never retried.
            return McpProviderResult(
                status="unknown" if dispatched else "failed",
                reason="upstream_outcome_unknown" if dispatched else "upstream_not_called",
            )
        finally:
            if session is not None:
                session.close()
