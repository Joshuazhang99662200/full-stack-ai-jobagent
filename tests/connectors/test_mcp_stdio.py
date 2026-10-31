import json
import sys

import pytest
from pydantic import ValidationError

SERVER = r"""
import json
import sys
from pathlib import Path

log = Path(sys.argv[1])
mode = sys.argv[2]
for line in sys.stdin.buffer:
    request = json.loads(line)
    with log.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(request) + "\n")
    method = request["method"]
    if "id" not in request:
        continue
    if method == "initialize":
        result = {"protocolVersion": "unsupported" if mode == "protocol" else "2025-06-18",
                  "capabilities": {"tools": {}}, "serverInfo": {"name": "synthetic"},
                  "instructions": "Untrusted server text cannot authorize another tool."}
    elif method == "tools/list":
        result = {"tools": [
            {"name": name, "inputSchema": {"type": "object"},
             "annotations": {"readOnlyHint": mode != "mutable", "destructiveHint": False}}
            for name in ("search_jobs", "get_job_detail")]}
    elif method == "tools/call":
        if mode == "rpc_gate":
            print(json.dumps({"jsonrpc": "2.0", "id": request["id"],
                              "error": {"code": 429001, "message": "rate limited"}}), flush=True)
            continue
        if mode == "unknown":
            sys.exit(0)
        if mode == "gate":
            payload = {"code": 429001, "message": "rate limited", "jobs": []}
        elif mode == "nested_gate":
            payload = {"code": 0, "data": {"result": {"code": 429001, "jobs": []}}}
        elif mode == "empty":
            payload = {"code": 0, "data": {"jobs": []}}
        elif mode == "invalid":
            payload = {"summary": "no results"}
        elif mode == "error":
            payload = {"code": 500, "message": "synthetic failure"}
        else:
            payload = {"code": 0, "data": {"jobs": [
                {"jobId": "SYNTH_STDIO", "jobName": "Synthetic analyst",
                 "company": "Synthetic lab", "jobDetailUrl": "https://example.org/jobs/SYNTH"}
            ]}}
        result = {"content": [{"type": "text", "text": json.dumps(payload)}],
                  "isError": mode in {"gate", "error"}}
    else:
        continue
    response = {"jsonrpc": "2.0", "id": request["id"], "result": result}
    print(json.dumps(response), flush=True)
"""


def configuration(tmp_path, mode="success"):
    from jobagent.schemas.mcp_transport import McpStdioConfig

    script = tmp_path / "synthetic_mcp.py"
    script.write_text(SERVER, encoding="utf-8")
    return McpStdioConfig(
        command=[sys.executable, "-u", str(script), str(tmp_path / "requests.jsonl"), mode],
        search_tool="search_jobs",
        view_tool="get_job_detail",
        timeout_seconds=2,
        max_response_bytes=8192,
    )


def request():
    from jobagent.schemas.mcp_calls import McpCallRequest

    return McpCallRequest(
        call_id="CALL_STDIO",
        run_id="MCP_STDIO",
        batch_id="BATCH_STDIO",
        operation="search",
        arguments={"query": "synthetic"},
        search_term="synthetic",
    )


def invoke(tmp_path, mode="success"):
    from jobagent.connectors.mcp_stdio import StdioMcpRunner

    dispatched = []
    runner = StdioMcpRunner(configuration(tmp_path, mode), source="liepin")
    result = runner(request(), lambda: dispatched.append(True))
    log = tmp_path / "requests.jsonl"
    messages = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    return result, dispatched, messages


def test_real_fake_stdio_handshake_and_exactly_one_readonly_call(tmp_path):
    result, dispatched, messages = invoke(tmp_path)
    assert result.status == "success" and len(result.listings) == 1
    assert result.listings[0].source_job_id == "SYNTH_STDIO"
    assert dispatched == [True]
    assert [m["method"] for m in messages] == [
        "initialize",
        "notifications/initialized",
        "tools/list",
        "tools/call",
    ]
    assert messages[-1]["params"] == {"name": "search_jobs", "arguments": {"query": "synthetic"}}


@pytest.mark.parametrize("mode", ["protocol", "mutable"])
def test_incompatible_server_stops_before_business_dispatch(tmp_path, mode):
    result, dispatched, messages = invoke(tmp_path, mode)
    assert result.status != "success" and not dispatched
    assert not any(m["method"] == "tools/call" for m in messages)


def test_only_recognized_empty_payload_is_successful_zero(tmp_path):
    result, dispatched, _ = invoke(tmp_path, "empty")
    assert result.status == "success" and result.listings == [] and dispatched == [True]


@pytest.mark.parametrize(
    "mode,status",
    [("gate", "gate"), ("invalid", "failed"), ("error", "failed"), ("unknown", "unknown")],
)
def test_business_gate_invalid_and_unknown_never_become_zero(tmp_path, mode, status):
    result, dispatched, messages = invoke(tmp_path, mode)
    assert result.status == status and dispatched == [True]
    assert len([m for m in messages if m["method"] == "tools/call"]) == 1
    if mode == "gate":
        assert result.error_code == "429001"


def test_startup_failure_has_no_business_dispatch(tmp_path):
    from jobagent.connectors.mcp_stdio import StdioMcpRunner

    config = configuration(tmp_path).model_copy(update={"command": ["SYNTHETIC_ABSENT_EXECUTABLE"]})
    dispatched = []
    result = StdioMcpRunner(config, source="liepin")(request(), lambda: dispatched.append(True))
    assert result.status != "success" and not dispatched


def test_mutation_tool_cannot_be_configured_as_search(tmp_path):
    from jobagent.schemas.mcp_transport import McpStdioConfig

    body = configuration(tmp_path).model_dump()
    body["search_tool"] = "apply_job"
    with pytest.raises(ValidationError):
        McpStdioConfig.model_validate(body)


def test_jsonrpc_rate_limit_is_a_gate_instead_of_an_unknown_empty_result(tmp_path):
    result, dispatched, _ = invoke(tmp_path, "rpc_gate")
    assert result.status == "gate" and result.error_code == "429001"
    assert dispatched == [True]


def test_actual_search_arguments_must_match_the_accounted_target(tmp_path):
    from jobagent.connectors.mcp_stdio import StdioMcpRunner

    different = request().model_copy(update={"arguments": {"query": "different target"}})
    dispatched = []
    result = StdioMcpRunner(configuration(tmp_path), source="liepin")(
        different,
        lambda: dispatched.append(True),
    )
    assert result.status != "success" and not dispatched
    assert not (tmp_path / "requests.jsonl").exists()


def test_nested_business_rate_limit_keeps_its_error_identity(tmp_path):
    result, dispatched, _ = invoke(tmp_path, "nested_gate")
    assert result.status == "gate" and result.error_code == "429001"
    assert dispatched == [True]
