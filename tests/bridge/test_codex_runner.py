import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from jobagent.bridge.codex_runner import CodexTextRunner
from jobagent.errors import InvalidProviderOutputError, UserInterventionRequiredError
from jobagent.schemas.coordinator import CodexTextRecord, CodexTextReply, CodexTextRequest


def request() -> CodexTextRequest:
    return CodexTextRequest(
        request_id="CTX_TEST",
        instruction="Summarize the supplied synthetic record.",
        records=[CodexTextRecord(record_id="TEST_1", kind="jd", text="Synthetic role only.")],
    )


def test_runner_uses_text_stdin_fixed_model_and_narrow_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def fake_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen.update(args=args, **kwargs)
        assert kwargs["cwd"].is_dir()
        assert Path(args[args.index("--output-schema") + 1]).is_file()
        result = Path(args[args.index("--output-last-message") + 1])
        result.write_text(
            CodexTextReply(request_id="CTX_TEST", text="Ready.").model_dump_json(), encoding="utf-8"
        )
        return subprocess.CompletedProcess(args, 0, '{"type":"turn.completed"}\n', "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = CodexTextRunner("codex.exe", tmp_path).run(request(), CodexTextReply)
    assert result.text == "Ready."
    args = seen["args"]
    assert args[args.index("--model") + 1] == "gpt-6.1-sol"
    assert args[args.index("--sandbox") + 1] == "read-only"
    assert "--ignore-user-config" in args and "--ignore-rules" not in args
    assert not any("dangerously" in arg for arg in args)
    assert "--image" not in args and "-i" not in args
    assert "tools.view_image=false" not in args
    disabled = {args[i + 1] for i, arg in enumerate(args) if arg == "--disable"}
    assert {
        "view_image",
        "shell_tool",
        "computer_use",
        "browser_use",
        "apps",
        "plugins",
        "unified_exec",
        "unified_exec_tty",
        "browser_use_full_cdp_access",
        "tool_suggest",
    } <= disabled
    assert "code_mode" in disabled and "code_mode_host" not in disabled
    assert "Synthetic role only." in seen["input"]
    assert "Synthetic role only." not in " ".join(args)
    assert seen["shell"] is False and seen["timeout"] == 120
    assert not seen["cwd"].exists()


@pytest.mark.parametrize(
    "extra",
    [
        {"image_url": "https://example.org/image.png"},
        {"screenshot_path": "C:/private/screenshot.png"},
    ],
)
def test_image_fields_are_not_part_of_text_request(extra: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        CodexTextRequest.model_validate(request().model_dump() | extra)


def test_inline_image_data_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Image"):
        CodexTextRecord(record_id="BAD", kind="jd", text="data:image/png;base64,AA==")


@pytest.mark.parametrize(
    "exit_code,body",
    [(1, ""), (0, ""), (0, "not json"), (0, '{"request_id":"CTX_OTHER","text":"wrong"}')],
)
def test_missing_invalid_or_unrelated_output_is_not_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    exit_code: int,
    body: str,
) -> None:
    def fake_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if body:
            Path(args[args.index("--output-last-message") + 1]).write_text(body, encoding="utf-8")
        return subprocess.CompletedProcess(
            args, exit_code, '{"type":"turn.completed"}\n', "private subprocess diagnostic"
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises((InvalidProviderOutputError, UserInterventionRequiredError)) as caught:
        CodexTextRunner("codex.exe", tmp_path).run(request(), CodexTextReply)
    assert "private subprocess diagnostic" not in str(caught.value)
    if "CTX_OTHER" in body:
        assert "different request" in str(caught.value)


def test_timeout_does_not_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def fake_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        raise subprocess.TimeoutExpired(args, 120)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(UserInterventionRequiredError):
        CodexTextRunner("codex.exe", tmp_path).run(request(), CodexTextReply)
    assert calls == 1


def test_cli_tool_activity_is_refused_even_with_valid_final_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        Path(args[args.index("--output-last-message") + 1]).write_text(
            CodexTextReply(request_id="CTX_TEST", text="Ready.").model_dump_json(), encoding="utf-8"
        )
        event = {"type": "item.completed", "item": {"type": "mcp_tool_call"}}
        return subprocess.CompletedProcess(args, 0, json.dumps(event) + "\n", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(InvalidProviderOutputError):
        CodexTextRunner("codex.exe", tmp_path).run(request(), CodexTextReply)


def test_startup_configuration_error_is_reported_as_configuration_failure() -> None:
    event = {"type": "item.completed", "item": {"type": "error", "message": "private diagnostic"}}
    with pytest.raises(InvalidProviderOutputError, match="configuration") as caught:
        CodexTextRunner._check_events(json.dumps(event) + '\n{"type":"turn.completed"}\n')
    assert "private diagnostic" not in str(caught.value)
