import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jobagent.bridge import mailbox
from jobagent.errors import ContractValidationError

NOW = datetime(2026, 10, 20, 5, 30, tzinfo=UTC)  # 13:30 in Shanghai
PENDING = [{"ask_id": "OASK_1", "batch_id": "OBATCH_1", "question": "可行哪几条"}]


def lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_request_is_appended_with_a_local_id(tmp_path: Path) -> None:
    first = mailbox.post_to_claude_code(
        tmp_path, "request", text="用户原话", summary="摘要", pending=[], now=NOW
    )
    second = mailbox.post_to_claude_code(
        tmp_path, "request", text="又一句", summary="摘要二", pending=[], now=NOW
    )

    assert first["id"] == "IN_20261020_1330_01"
    assert second["id"] == "IN_20261020_1330_02"
    assert first["from"] == "cowork"
    assert [e["id"] for e in lines(tmp_path / mailbox.INBOX)] == [first["id"], second["id"]]


def test_approval_must_answer_a_question_that_is_still_pending(tmp_path: Path) -> None:
    entry = mailbox.post_to_claude_code(
        tmp_path, "approval", ask_id="OASK_1", batch_id="OBATCH_1", items="1-3",
        answer="可行 1-3", pending=PENDING, now=NOW,
    )
    assert entry["answer"] == "可行 1-3"

    with pytest.raises(ContractValidationError):
        mailbox.post_to_claude_code(
            tmp_path, "approval", ask_id="OASK_9", batch_id="OBATCH_1", items="1",
            answer="可行", pending=PENDING, now=NOW,
        )
    with pytest.raises(ContractValidationError):
        mailbox.post_to_claude_code(
            tmp_path, "approval", ask_id="OASK_1", batch_id="OBATCH_1", items="1",
            answer="  ", pending=PENDING, now=NOW,
        )


def test_unknown_kinds_and_empty_requests_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ContractValidationError):
        mailbox.post_to_claude_code(tmp_path, "send", text="x", summary="x", pending=[], now=NOW)
    with pytest.raises(ContractValidationError):
        mailbox.post_to_claude_code(tmp_path, "request", text="", summary="x", pending=[], now=NOW)
    assert not (tmp_path / mailbox.INBOX).exists()


def test_unprocessed_inbox_drops_entries_with_a_receipt(tmp_path: Path) -> None:
    a = mailbox.post_to_claude_code(tmp_path, "request", text="a", summary="a", pending=[], now=NOW)
    b = mailbox.post_to_claude_code(tmp_path, "request", text="b", summary="b", pending=[], now=NOW)

    receipt = mailbox.acknowledge(tmp_path, a["id"], "accepted", "排在第 1 步", now=NOW)

    assert receipt["status"] == "accepted"
    assert [e["id"] for e in mailbox.unprocessed(tmp_path)] == [b["id"]]
    assert [r["id"] for r in mailbox.receipts(tmp_path)] == [a["id"]]
    with pytest.raises(ContractValidationError):
        mailbox.acknowledge(tmp_path, "IN_NOPE", "accepted", "x", now=NOW)
    with pytest.raises(ContractValidationError):
        mailbox.acknowledge(tmp_path, b["id"], "maybe", "x", now=NOW)


def test_notes_from_claude_code_are_read_after_a_given_id(tmp_path: Path) -> None:
    first = mailbox.notify_cowork(tmp_path, "审批单已生成", refs=["OBATCH_1"], now=NOW)
    second = mailbox.notify_cowork(tmp_path, "巡检恢复", now=NOW)

    assert first["id"] == "OUT_20261020_1330_01"
    assert [n["id"] for n in mailbox.notes(tmp_path)] == [first["id"], second["id"]]
    assert [n["id"] for n in mailbox.notes(tmp_path, after=first["id"])] == [second["id"]]


def test_session_identities_are_registered_and_stamped_on_messages(tmp_path: Path) -> None:
    mailbox.register_session(
        tmp_path, "claude_code", "d4809772-89b4-4b6c-aa9f-763a7c920703",
        name="Job hunt patrol setup", now=NOW,
    )

    peers = mailbox.peers(tmp_path)
    assert peers["claude_code"]["session_id"] == "d4809772-89b4-4b6c-aa9f-763a7c920703"
    note = mailbox.notify_cowork(tmp_path, "hi", now=NOW)
    assert note["from_session"] == "d4809772-89b4-4b6c-aa9f-763a7c920703"
    entry = mailbox.post_to_claude_code(
        tmp_path, "request", text="x", summary="x", pending=[], now=NOW
    )
    assert entry["to_session"] == "d4809772-89b4-4b6c-aa9f-763a7c920703"
    with pytest.raises(ContractValidationError):
        mailbox.register_session(tmp_path, "somebody", "id", now=NOW)
