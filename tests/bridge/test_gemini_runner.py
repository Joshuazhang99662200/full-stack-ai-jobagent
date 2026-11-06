"""The Gemini CLI runner keeps the same text-only, validated boundary as the Codex runner."""

import json
import stat
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
    """A stand-in executable that records what it received and prints `body`."""
    script = tmp_path / "fake-gemini"
    log = tmp_path / "received.json"
    script.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        f"json.dump({{'argv': sys.argv[1:], 'stdin': sys.stdin.read(),"
        f" 'cwd_files': os.listdir('.')}}, open({str(log)!r}, 'w'))\n"
        f"sys.stdout.write({body!r})\n"
        f"sys.exit({code})\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def runner(tmp_path: Path, script: Path) -> GeminiTextRunner:
    config = GeminiCliConfig(argv=[str(script), "--output-format", "json"], timeout_seconds=30)
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
