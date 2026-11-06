"""The Gemini CLI runner keeps the same text-only, validated boundary as the Codex runner."""

import json
import sys
from pathlib import Path

import pytest

from jobagent.bridge.gemini_runner import GeminiTextRunner
from jobagent.errors import InvalidProviderOutputError, UserInterventionRequiredError
from jobagent.schemas.common import ContractModel
from jobagent.schemas.coordinator import CodexTextRecord, CodexTextRequest
from jobagent.schemas.roleplay import GeminiCliConfig


class Answer(ContractModel):
    text: str
    score: int


REQUEST = CodexTextRequest(
    request_id="CTX_SYNTHETIC",
    instruction="Return a synthetic answer.",
    records=[CodexTextRecord(record_id="R1", kind="evidence", text="Synthetic record.")],
)


def fake_gemini(tmp_path: Path, body: str, *, code: int = 0) -> Path:
    """A stand-in script that records what it received and prints `body`. It runs
    through the current interpreter, so the tests also work where shebangs do not."""
    script = tmp_path / "fake-gemini.py"
    log = tmp_path / "received.json"
    script.write_text(
        "import json, os, sys\n"
        "sys.stdin.reconfigure(encoding='utf-8')\n"
        "sys.stdout.reconfigure(encoding='utf-8')\n"
        f"json.dump({{'argv': sys.argv[1:], 'stdin': sys.stdin.read(),"
        f" 'cwd_files': os.listdir('.')}}, open({str(log)!r}, 'w', encoding='utf-8'))\n"
        f"sys.stdout.write({body!r})\n"
        f"sys.exit({code})\n",
        encoding="utf-8",
    )
    return script


def runner(tmp_path: Path, script: Path) -> GeminiTextRunner:
    config = GeminiCliConfig(
        argv=[sys.executable, str(script), "--output-format", "json"], timeout_seconds=30
    )
    return GeminiTextRunner(config, tmp_path / "runtime")


def envelope(response: str, tool_calls: int | None = 0) -> str:
    data: dict[str, object] = {"response": response}
    if tool_calls is not None:
        data["stats"] = {"tools": {"totalCalls": tool_calls}}
    return json.dumps(data)


def test_valid_reply_is_parsed_from_a_fenced_json_response(tmp_path):
    script = fake_gemini(tmp_path, envelope('```json\n{"text": "ok", "score": 3}\n```'))
    reply = runner(tmp_path, script).run(REQUEST, Answer)

    assert reply == Answer(text="ok", score=3)
    received = json.loads((tmp_path / "received.json").read_text())
    assert received["argv"] == ["--output-format", "json"]
    assert received["cwd_files"] == []  # an empty working directory, nothing to read
    assert "CTX_SYNTHETIC" in received["stdin"] and '"score"' in received["stdin"]
    assert "Do not use tools" in received["stdin"]


def test_any_tool_activity_is_outside_the_text_only_boundary(tmp_path):
    script = fake_gemini(tmp_path, envelope('{"text": "ok", "score": 3}', tool_calls=1))
    with pytest.raises(InvalidProviderOutputError, match="Tool"):
        runner(tmp_path, script).run(REQUEST, Answer)


def test_missing_tool_statistics_are_not_treated_as_proof_of_no_tools(tmp_path):
    script = fake_gemini(tmp_path, envelope('{"text": "ok", "score": 3}', tool_calls=None))
    with pytest.raises(InvalidProviderOutputError, match="statistics"):
        runner(tmp_path, script).run(REQUEST, Answer)


@pytest.mark.parametrize("body", ["not json", envelope("no object here"), envelope('{"text": 1}')])
def test_invalid_output_fails_closed(tmp_path, body):
    with pytest.raises(InvalidProviderOutputError):
        runner(tmp_path, fake_gemini(tmp_path, body)).run(REQUEST, Answer)


def test_failed_process_is_handed_back_without_retry(tmp_path):
    script = fake_gemini(tmp_path, "boom", code=2)
    with pytest.raises(UserInterventionRequiredError):
        runner(tmp_path, script).run(REQUEST, Answer)
    assert json.loads((tmp_path / "received.json").read_text())["argv"]


def test_prose_around_the_json_object_is_tolerated(tmp_path):
    script = fake_gemini(tmp_path, envelope('Sure:\n{"text": "plain", "score": 1}\nDone.'))
    assert runner(tmp_path, script).run(REQUEST, Answer).text == "plain"


def test_config_needs_an_explicit_bounded_timeout():
    with pytest.raises(ValueError):
        GeminiCliConfig(argv=["gemini"], timeout_seconds=0)
    with pytest.raises(ValueError):
        GeminiCliConfig(argv=[], timeout_seconds=30)


@pytest.mark.parametrize("flag", ["--dangerously-skip-permissions", "--yolo", "-y"])
def test_config_refuses_flags_that_auto_approve_tools(flag):
    with pytest.raises(ValueError, match="auto-approve"):
        GeminiCliConfig(argv=["agy", flag], timeout_seconds=30)


# --- Antigravity CLI (`agy`) stream-json protocol -----------------------------------

AGY_ARGV = ["-p=", "--input-format", "stream-json", "--output-format", "stream-json"]


def agy_events(
    response: str,
    *,
    steps: list[dict[str, object]] | None = None,
    status: str = "SUCCESS",
    denied: list[dict[str, str]] | None = None,
) -> str:
    """NDJSON shaped like `agy --output-format stream-json` prints it."""
    if steps is None:
        steps = [
            {"step_index": 0, "state": "DONE", "step_type": "user_input"},
            {"step_index": 1, "state": "DONE", "step_type": "agent_response",
             "text_delta": response},
        ]
    result: dict[str, object] = {"status": status, "response": response, "num_turns": 1}
    if denied is not None:
        result["denied_actions"] = denied
    lines: list[dict[str, object]] = [{"event": "init", "init": {"model": "gemini-3.8-flash"}}]
    lines += [{"event": "step_update", "step_update": step} for step in steps]
    lines.append({"event": "result", "result": result})
    return "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines)


def agy_runner(tmp_path: Path, script: Path) -> GeminiTextRunner:
    config = GeminiCliConfig(
        argv=[sys.executable, str(script), *AGY_ARGV], timeout_seconds=30,
        protocol="agy_stream_json",
    )
    return GeminiTextRunner(config, tmp_path / "runtime")


def test_agy_task_goes_in_as_one_stream_json_user_message(tmp_path):
    script = fake_gemini(tmp_path, agy_events('{"text": "好", "score": 2}'))
    reply = agy_runner(tmp_path, script).run(REQUEST, Answer)

    assert reply == Answer(text="好", score=2)
    received = json.loads((tmp_path / "received.json").read_text(encoding="utf-8"))
    assert received["argv"] == AGY_ARGV
    assert received["cwd_files"] == []
    lines = received["stdin"].splitlines()
    assert len(lines) == 1
    message = json.loads(lines[0])
    assert message["event"] == "user"
    content = message["message"]["content"]
    assert "CTX_SYNTHETIC" in content and "Do not use tools" in content


def tool_steps(kind: str) -> list[dict[str, object]]:
    return [
        {"step_index": 0, "state": "DONE", "step_type": "user_input"},
        {"step_index": 1, "state": "DONE", "step_type": "agent_response"},
        {"step_index": 2, "state": "DONE", "step_type": kind, "tool_name": "read_file"},
        {"step_index": 3, "state": "DONE", "step_type": "agent_response"},
    ]


@pytest.mark.parametrize("kind", ["tool", "browser_subagent"])
def test_agy_tool_or_unknown_step_is_outside_the_text_only_boundary(tmp_path, kind):
    body = agy_events('{"text": "ok", "score": 3}', steps=tool_steps(kind))
    with pytest.raises(InvalidProviderOutputError, match="Tool"):
        agy_runner(tmp_path, fake_gemini(tmp_path, body)).run(REQUEST, Answer)


def test_agy_denied_tool_attempt_is_still_tool_activity(tmp_path):
    body = agy_events(
        '{"text": "ok", "score": 3}',
        denied=[{"action": "command", "display_name": "RunCommand"}],
    )
    with pytest.raises(InvalidProviderOutputError, match="Tool"):
        agy_runner(tmp_path, fake_gemini(tmp_path, body)).run(REQUEST, Answer)


def test_agy_stream_without_step_events_is_not_proof_of_no_tools(tmp_path):
    body = agy_events('{"text": "ok", "score": 3}', steps=[])
    with pytest.raises(InvalidProviderOutputError, match="step"):
        agy_runner(tmp_path, fake_gemini(tmp_path, body)).run(REQUEST, Answer)


def test_agy_unsuccessful_result_is_handed_back_without_retry(tmp_path):
    script = fake_gemini(tmp_path, agy_events("", status="ERROR"))
    with pytest.raises(UserInterventionRequiredError):
        agy_runner(tmp_path, script).run(REQUEST, Answer)


@pytest.mark.parametrize(
    "body",
    [
        "not json\n",
        json.dumps({"response": '{"text": "ok", "score": 3}'}),  # plain JSON, not a stream
        agy_events('{"text": "ok", "score": 3}').rsplit("\n", 2)[0] + "\n",  # no result event
        agy_events("no object here"),
    ],
)
def test_agy_invalid_stream_fails_closed(tmp_path, body):
    with pytest.raises(InvalidProviderOutputError):
        agy_runner(tmp_path, fake_gemini(tmp_path, body)).run(REQUEST, Answer)
