"""A local MCP server over stdio, so a chat front end can see the ledger and talk back.

Run: python -m jobagent.bridge.mcp_server --database .jobagent/jobagent.sqlite3

It speaks the MCP stdio transport (one JSON-RPC 2.0 message per line) with no
dependency beyond the standard library. Ledger tools only read. The one write
appends to the Cowork -> Claude Code mailbox (see jobagent.bridge.mailbox);
sending, approving and drafting stay with the CLI and the person's approvals.
"""

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from jobagent.bridge import mailbox, status
from jobagent.console.projection import definitions as console_definitions
from jobagent.console.projection import snapshot as console_snapshot

PROTOCOL_VERSION = "2025-06-18"

Tool = tuple[str, dict[str, Any], Callable[["McpServer", dict[str, Any]], Any]]

TEXT = {"type": "string"}

TOOLS: list[Tool] = [
    (
        "console_definitions",
        {"description": "Read complete authoritative console JSON schemas; no private data."},
        lambda srv, args: console_definitions(),
    ),
    (
        "console_list",
        {"description": "Read candidate-scoped console snapshot with complete business fields, "
         "history and source diagnostics. Does not approve, send or alter run state.",
         "candidate_id": TEXT},
        lambda srv, args: console_snapshot(
            srv.database, srv.workspace, str(args.get("candidate_id", "")),
        ).model_dump(mode="json"),
    ),
    (
        "status_today",
        {"description": "Today's state per board (Boss, 猎聘, 智联): sends, approved queue, "
         "questions awaiting the person, new recruiter mail, detail reads, latest snapshot."},
        lambda srv, _args: status.status_today(srv.database),
    ),
    (
        "pending_approvals",
        {"description": "Approval questions not answered yet, with the exact greeting texts. "
         "Show them to the person word for word; this tool approves nothing."},
        lambda srv, _args: status.pending_approvals(srv.database),
    ),
    (
        "patrol_history",
        {"description": "Recent patrol checks with start, finish and whether one was cut off.",
         "limit": {"type": "integer", "minimum": 1, "maximum": 50}},
        lambda srv, args: status.patrol_history(srv.database, int(args.get("limit", 10))),
    ),
    (
        "new_jobs",
        {"description": "Postings stored in the last hours with their latest match decision.",
         "hours": {"type": "integer", "minimum": 1, "maximum": 168}},
        lambda srv, args: status.new_jobs(srv.database, int(args.get("hours", 24))),
    ),
    (
        "post_to_claude_code",
        {"description": "Leave the person's approval or request for the Claude Code main "
         "session. kind=approval needs ask_id and batch_id taken from pending_approvals, "
         "items as numbered there, and answer as the person's exact words; it is refused "
         "when that question is no longer pending. kind=request needs text (exact words) "
         "and summary. This registers nothing: the main session does that and writes a "
         "receipt.",
         "kind": {"type": "string", "enum": list(mailbox.KINDS)},
         "text": TEXT, "summary": TEXT, "ask_id": TEXT, "batch_id": TEXT,
         "items": TEXT, "answer": TEXT, "note": TEXT},
        lambda srv, args: mailbox.post_to_claude_code(
            srv.mailbox_folder, str(args.get("kind", "")),
            pending=status.pending_approvals(srv.database),
            **{k: args.get(k) for k in
               ("text", "summary", "ask_id", "batch_id", "items", "answer", "note")},
        ),
    ),
    (
        "receipts",
        {"description": "The main session's receipt for each mailbox entry: accepted, "
         "registered, done or rejected, with a reason."},
        lambda srv, _args: mailbox.receipts(srv.mailbox_folder),
    ),
    (
        "notes_from_claude_code",
        {"description": "Notes the main session left for Cowork, oldest first; pass after "
         "with the last id you have read to get only newer ones.",
         "after": TEXT},
        lambda srv, args: mailbox.notes(srv.mailbox_folder, args.get("after")),
    ),
    (
        "peer_sessions",
        {"description": "Which session plays which role (claude_code, cowork), with ids."},
        lambda srv, _args: mailbox.peers(srv.mailbox_folder),
    ),
]


def _schema(spec: dict[str, Any]) -> dict[str, Any]:
    properties = {k: v for k, v in spec.items() if k != "description"}
    return {"type": "object", "properties": properties, "additionalProperties": False}


class McpServer:
    database: Path
    mailbox_folder: Path
    workspace: Path

    def __init__(
        self, database: Path, mailbox_folder: Path | None = None, *, workspace: Path | None = None,
    ) -> None:
        self.database = database
        self.workspace = workspace or database.resolve().parent.parent
        # The ledger sits in <repo>/.jobagent/, the private folder in <repo>/candidate/.
        self.mailbox_folder = mailbox_folder or database.parent.parent / "candidate" / "private"
        self.tools = {name: (spec, run) for name, spec, run in TOOLS}

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        rid = message.get("id")
        if rid is None:  # a notification: never answered
            return None
        if method == "initialize":
            return self._ok(rid, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "jobagent", "version": "0.2.0"},
            })
        if method == "ping":
            return self._ok(rid, {})
        if method == "tools/list":
            return self._ok(rid, {"tools": [
                {"name": name, "description": spec["description"], "inputSchema": _schema(spec)}
                for name, (spec, _run) in self.tools.items()
            ]})
        if method == "tools/call":
            params = message.get("params") or {}
            name = params.get("name")
            if name not in self.tools:
                return self._ok(rid, self._text(f"Unknown tool: {name}", error=True))
            try:
                result = self.tools[name][1](self, params.get("arguments") or {})
            except Exception as error:  # report, never crash the transport
                return self._ok(rid, self._text(f"{type(error).__name__}: {error}", error=True))
            return self._ok(rid, self._text(json.dumps(result, ensure_ascii=False, default=str)))
        return {"jsonrpc": "2.0", "id": rid,
                "error": {"code": -32601, "message": f"Method not found: {method}"}}

    @staticmethod
    def _ok(rid: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    @staticmethod
    def _text(text: str, *, error: bool = False) -> dict[str, Any]:
        return {"content": [{"type": "text", "text": text}], "isError": error}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default=".jobagent/jobagent.sqlite3")
    parser.add_argument("--mailbox", default=None, help="Defaults to <repo>/candidate/private.")
    parser.add_argument("--workspace", default=None,
                        help="Run workspace; defaults to the database parent's parent.")
    args = parser.parse_args()
    server = McpServer(
        Path(args.database), Path(args.mailbox) if args.mailbox else None,
        workspace=Path(args.workspace) if args.workspace else None,
    )
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    for line in stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except ValueError:
            continue
        reply = server.handle(message)
        if reply is not None:
            stdout.write(json.dumps(reply, ensure_ascii=False).encode("utf-8") + b"\n")
            stdout.flush()


if __name__ == "__main__":
    main()
