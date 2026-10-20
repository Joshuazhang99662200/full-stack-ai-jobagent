import json
from pathlib import Path

from jobagent.bridge import mailbox
from tests.cli.test_outreach import invoke


def test_claude_code_reads_acknowledges_and_replies(tmp_path: Path) -> None:
    box = ("--mailbox", str(tmp_path))
    entry = mailbox.post_to_claude_code(
        tmp_path, "request", text="原话", summary="摘要", pending=[]
    )

    code, register = invoke(
        "mailbox", "register-session", "claude_code", "SESSION_1", "--name", "主会话", *box
    )
    assert code == 0 and isinstance(register, dict)
    code, inbox = invoke("mailbox", "inbox", *box)
    assert code == 0 and isinstance(inbox, list)
    assert [e["id"] for e in inbox] == [entry["id"]]

    code, receipt = invoke(
        "mailbox", "ack", entry["id"], "--status", "accepted", "--reason", "排第 1 步", *box
    )
    assert code == 0 and isinstance(receipt, dict) and receipt["from_session"] == "SESSION_1"
    code, inbox = invoke("mailbox", "inbox", *box)
    assert inbox == []

    code, note = invoke("mailbox", "notify", "审批单已生成", "--ref", "OBATCH_1", *box)
    assert code == 0 and isinstance(note, dict) and note["refs"] == ["OBATCH_1"]
    code, peers = invoke("mailbox", "peers", *box)
    assert isinstance(peers, dict) and peers["claude_code"]["session_id"] == "SESSION_1"


def test_ack_of_an_unknown_entry_fails(tmp_path: Path) -> None:
    code, error = invoke(
        "mailbox", "ack", "IN_NONE", "--status", "accepted", "--reason", "x",
        "--mailbox", str(tmp_path),
    )
    assert code == 1 and isinstance(error, dict) and "error" in error
    assert not (tmp_path / mailbox.RECEIPTS).exists()
    assert json.dumps(error, ensure_ascii=False)
