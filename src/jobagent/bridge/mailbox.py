"""An append-only mailbox between the Cowork front end and the Claude Code main session.

Cowork posts the person's approvals and requests; the main session reads them,
acts on them under the usual gates, writes a receipt per entry and leaves notes.
Nothing here approves, sends or touches the SQLite ledger: an approval in the
mailbox is a relayed answer that the main session still registers itself with
`outreach approve`, and only if the question is still pending.

Files live in the candidate's private folder, which never enters git:

- cowork_inbox.jsonl       Cowork -> Claude Code (approval | request)
- cowork_inbox_done.jsonl  Claude Code -> Cowork, one receipt per inbox entry
- cc_outbox.jsonl          Claude Code -> Cowork, free notes
- agent_peers.json         which session plays which role
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jobagent.errors import ContractValidationError
from jobagent.outreach.service import PLATFORM_DAY

INBOX = "cowork_inbox.jsonl"
RECEIPTS = "cowork_inbox_done.jsonl"
OUTBOX = "cc_outbox.jsonl"
PEERS = "agent_peers.json"

KINDS = ("approval", "request")
STATUSES = ("accepted", "registered", "done", "rejected")
ROLES = ("claude_code", "cowork")


def _read(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                entries.append(json.loads(line))
            except ValueError:
                continue  # a torn line never hides the ones after it
    return entries


def _append(path: Path, entry: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def _next_id(prefix: str, path: Path, now: datetime) -> str:
    stem = f"{prefix}_{now.astimezone(PLATFORM_DAY):%Y%m%d_%H%M}_"
    taken = sum(str(e.get("id", "")).startswith(stem) for e in _read(path))
    return f"{stem}{taken + 1:02d}"


def _stamp(now: datetime) -> str:
    return now.astimezone(PLATFORM_DAY).isoformat(timespec="seconds")


def _required(**fields: str | None) -> None:
    missing = [name for name, value in fields.items() if not (value or "").strip()]
    if missing:
        raise ContractValidationError(
            "Mailbox entry is missing fields.", details={"missing": missing}
        )


def peers(folder: Path) -> dict[str, Any]:
    path = folder / PEERS
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _session(folder: Path, role: str) -> str | None:
    session = peers(folder).get(role, {}).get("session_id")
    return str(session) if session else None


def register_session(
    folder: Path, role: str, session_id: str, *, name: str = "", now: datetime | None = None
) -> dict[str, Any]:
    if role not in ROLES:
        raise ContractValidationError(
            "Unknown session role.", details={"role": role, "roles": ROLES}
        )
    _required(session_id=session_id)
    known = peers(folder)
    known[role] = {
        "session_id": session_id.strip(),
        "name": name,
        "registered_at": _stamp(now or datetime.now(UTC)),
    }
    folder.mkdir(parents=True, exist_ok=True)
    (folder / PEERS).write_text(json.dumps(known, ensure_ascii=False, indent=2), encoding="utf-8")
    return known


def post_to_claude_code(
    folder: Path,
    kind: str,
    *,
    pending: list[dict[str, Any]],
    text: str | None = None,
    summary: str | None = None,
    ask_id: str | None = None,
    batch_id: str | None = None,
    items: str | None = None,
    answer: str | None = None,
    note: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Append one approval or request from Cowork, refusing what cannot be acted on."""
    now = now or datetime.now(UTC)
    if kind not in KINDS:
        raise ContractValidationError(
            "Unknown mailbox kind.", details={"kind": kind, "kinds": KINDS}
        )
    path = folder / INBOX
    entry: dict[str, Any] = {"id": _next_id("IN", path, now), "at": _stamp(now), "kind": kind}
    if kind == "approval":
        _required(ask_id=ask_id, batch_id=batch_id, items=items, answer=answer)
        # The question must still be open: an answer to a settled or unknown
        # question would be registered against nothing.
        if not any(p["ask_id"] == ask_id and p["batch_id"] == batch_id for p in pending):
            raise ContractValidationError(
                "That question is not pending; read pending_approvals again.",
                details={"ask_id": ask_id, "batch_id": batch_id},
            )
        entry |= {"ask_id": ask_id, "batch_id": batch_id, "items": items, "answer": answer}
    else:
        _required(text=text, summary=summary)
        entry |= {"text": text, "summary": summary}
    if note:
        entry["note"] = note
    entry["from"] = "cowork"
    if target := _session(folder, "claude_code"):
        entry["to_session"] = target
    return _append(path, entry)


def receipts(folder: Path) -> list[dict[str, Any]]:
    return _read(folder / RECEIPTS)


def unprocessed(folder: Path) -> list[dict[str, Any]]:
    done = {r.get("id") for r in receipts(folder)}
    return [e for e in _read(folder / INBOX) if e.get("id") not in done]


def acknowledge(
    folder: Path, entry_id: str, status: str, reason: str, *, now: datetime | None = None
) -> dict[str, Any]:
    if status not in STATUSES:
        raise ContractValidationError(
            "Unknown receipt status.", details={"status": status, "statuses": STATUSES}
        )
    _required(reason=reason)
    if not any(e.get("id") == entry_id for e in _read(folder / INBOX)):
        raise ContractValidationError("No such inbox entry.", details={"id": entry_id})
    receipt: dict[str, Any] = {
        "id": entry_id,
        "status": status,
        "reason": reason,
        "at": _stamp(now or datetime.now(UTC)),
    }
    if session := _session(folder, "claude_code"):
        receipt["from_session"] = session
    return _append(folder / RECEIPTS, receipt)


def notify_cowork(
    folder: Path, text: str, *, refs: list[str] | None = None, now: datetime | None = None
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    _required(text=text)
    path = folder / OUTBOX
    note: dict[str, Any] = {
        "id": _next_id("OUT", path, now),
        "at": _stamp(now),
        "text": text,
        "refs": refs or [],
        "from": "claude_code",
    }
    if session := _session(folder, "claude_code"):
        note["from_session"] = session
    return _append(path, note)


def notes(folder: Path, after: str | None = None) -> list[dict[str, Any]]:
    entries = _read(folder / OUTBOX)
    if after is None:
        return entries
    ids = [n.get("id") for n in entries]
    return entries[ids.index(after) + 1 :] if after in ids else entries
