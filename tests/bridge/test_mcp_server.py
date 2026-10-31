import json
from pathlib import Path

from jobagent.bridge import mailbox
from jobagent.bridge.mcp_server import McpServer
from tests.cli.test_outreach import drafted, invoke


def call(server: McpServer, method: str, params: dict | None = None, rid: int = 1) -> dict:
    reply = server.handle({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
    assert reply is not None
    return reply


def test_initialize_and_list_read_only_tools(tmp_path: Path) -> None:
    server = McpServer(tmp_path / "jobagent.sqlite3")

    init = call(server, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
    assert init["result"]["capabilities"] == {"tools": {}}
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None

    tools = {t["name"] for t in call(server, "tools/list")["result"]["tools"]}
    assert tools == {
        "status_today", "pending_approvals", "patrol_history", "new_jobs",
        "post_to_claude_code", "receipts", "notes_from_claude_code", "peer_sessions",
        "console_list", "console_definitions",
    }


def test_pending_approvals_lists_questions_that_have_no_answer_yet(tmp_path: Path) -> None:
    database, batch_id = drafted(tmp_path)
    _, ask = invoke("outreach", "ask", batch_id, "--database", str(database))
    assert isinstance(ask, dict)
    server = McpServer(database)

    reply = call(server, "tools/call", {"name": "pending_approvals", "arguments": {}})

    payload = json.loads(reply["result"]["content"][0]["text"])
    assert [p["ask_id"] for p in payload] == [ask["ask_id"]]
    assert "方便聊聊吗" in payload[0]["question"]


def test_status_and_unknown_tools(tmp_path: Path) -> None:
    database, _ = drafted(tmp_path)
    server = McpServer(database)

    reply = call(server, "tools/call", {"name": "status_today", "arguments": {}})
    status = json.loads(reply["result"]["content"][0]["text"])
    assert set(status["boards"]) == {"boss", "liepin", "zhaopin"}

    unknown = call(server, "tools/call", {"name": "send_everything", "arguments": {}})
    assert unknown["result"]["isError"] is True
    assert call(server, "no/such/method")["error"]["code"] == -32601


def test_superseded_questions_are_not_listed(tmp_path: Path) -> None:
    database, first = drafted(tmp_path)
    db = ("--database", str(database))
    invoke("outreach", "ask", first, *db)
    drafts = tmp_path / "drafts.json"
    _, second = invoke("outreach", "draft-batch", str(drafts), *db)
    assert isinstance(second, dict)
    second_id = second["batch"]["batch_id"]
    _, ask = invoke("outreach", "ask", second_id, *db)
    assert isinstance(ask, dict)
    invoke(
        "outreach", "approve", second_id, "--request", ask["ask_id"], "--items", "1-2",
        "--answer", "发 1-2", *db,
    )

    pending = McpServer(database).handle({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "pending_approvals", "arguments": {}},
    })

    assert pending is not None
    assert json.loads(pending["result"]["content"][0]["text"]) == []


def test_mailbox_round_trip_between_cowork_and_claude_code(tmp_path: Path) -> None:
    database, batch_id = drafted(tmp_path)
    _, ask = invoke("outreach", "ask", batch_id, "--database", str(database))
    assert isinstance(ask, dict)
    box = tmp_path / "private"
    server = McpServer(database, box)

    posted = call(server, "tools/call", {"name": "post_to_claude_code", "arguments": {
        "kind": "approval", "ask_id": ask["ask_id"], "batch_id": batch_id,
        "items": "1", "answer": "可行 1",
    }})
    entry = json.loads(posted["result"]["content"][0]["text"])
    assert posted["result"]["isError"] is False and entry["kind"] == "approval"

    stale = call(server, "tools/call", {"name": "post_to_claude_code", "arguments": {
        "kind": "approval", "ask_id": "OASK_GONE", "batch_id": batch_id,
        "items": "1", "answer": "可行",
    }})
    assert stale["result"]["isError"] is True

    mailbox.acknowledge(box, entry["id"], "registered", "已登记")
    mailbox.notify_cowork(box, "已登记 1 条")
    receipts = call(server, "tools/call", {"name": "receipts", "arguments": {}})
    assert json.loads(receipts["result"]["content"][0]["text"])[0]["status"] == "registered"
    notes = call(server, "tools/call", {"name": "notes_from_claude_code", "arguments": {}})
    assert json.loads(notes["result"]["content"][0]["text"])[0]["text"] == "已登记 1 条"


def test_mailbox_defaults_next_to_the_repository_private_folder(tmp_path: Path) -> None:
    server = McpServer(tmp_path / ".jobagent" / "jobagent.sqlite3")
    assert server.mailbox_folder == tmp_path / "candidate" / "private"
