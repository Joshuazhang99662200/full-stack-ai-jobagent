"""Read-only views of the local ledger, shared by the dashboard and the MCP bridge.

Nothing here sends, approves or changes state; it only reads the SQLite file.
"""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from jobagent.outreach.service import PLATFORM_DAY

PLATFORMS = (("boss", "Boss"), ("liepin", "猎聘"), ("zhaopin", "智联"))


def _connect(database: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{database}?mode=ro", uri=True)


def _rows(con: sqlite3.Connection, sql: str, *args: object) -> list[tuple[Any, ...]]:
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []


def _day_start(now: datetime) -> str:
    local = now.astimezone(PLATFORM_DAY)
    start = datetime.combine(local.date(), datetime.min.time(), PLATFORM_DAY)
    return start.astimezone(UTC).isoformat()


def status_today(database: Path, now: datetime | None = None) -> dict[str, Any]:
    """Per board: today's sends, the approved queue, questions waiting, new mail, reads."""
    now = now or datetime.now(UTC)
    since = _day_start(now)
    con = _connect(database)
    audits = [json.loads(r[0]) for r in _rows(con, "SELECT audit_json FROM outreach_audits")]
    batches = {
        r[0]: json.loads(r[1])
        for r in _rows(con, "SELECT batch_id, batch_json FROM outreach_batches")
    }
    approvals = [
        json.loads(r[0]) for r in _rows(con, "SELECT approval_json FROM outreach_approvals")
    ]
    asked = {r[0] for r in _rows(con, "SELECT batch_id FROM outreach_asks")}
    done = {(a["batch_id"], a["number"]) for a in audits}
    approved = {(ap["batch_id"], n) for ap in approvals for n in ap["approved_numbers"]}
    approved_batches = {ap["batch_id"] for ap in approvals}
    recent = (now - timedelta(days=2)).isoformat()

    boards: dict[str, Any] = {}
    for key, label in PLATFORMS:
        todays = [a for a in audits if a["platform"] == key and a["recorded_at"] >= since]
        items = [
            (bid, item)
            for bid, batch in batches.items()
            for item in batch["items"]
            if item["platform"] == key
        ]
        snapshot = _rows(
            con,
            "SELECT snapshot_json FROM patrol_snapshots WHERE platform = ? "
            "ORDER BY captured_at DESC LIMIT 1",
            key,
        )
        snap = json.loads(snapshot[0][0]) if snapshot else None
        companies = {item["company"] for _, item in items}
        pulled = [
            i
            for i in (snap["items"] if snap else [])
            if i.get("last_from") == "system"
            and not any(i.get("company") and i["company"] in c for c in companies)
        ]
        inbound = _rows(
            con,
            "SELECT count(*) FROM conversation_events e JOIN conversations c "
            "ON c.conversation_id = e.conversation_id "
            "WHERE c.platform = ? AND e.kind = 'inbound' AND e.recorded_at >= ?",
            key,
            since,
        )
        reads = _rows(
            con,
            "SELECT count(*) FROM job_provenance WHERE source = ? AND collected_at >= ?",
            key,
            since,
        )
        failed = [a for a in todays if a["result"] in ("failed", "intervention")]
        sent = sum(a["result"] == "sent" for a in todays)
        pending = [
            (bid, item) for bid, item in items
            if (bid, item["number"]) in approved and (bid, item["number"]) not in done
        ]
        awaiting = [
            (bid, item) for bid, item in items
            if bid in asked and bid not in approved_batches
            and batches[bid].get("created_at", "") >= recent
        ]
        total = sent + len(failed) + len(pending)
        boards[key] = {
            "label": label,
            "sent_today": sent,
            "failed_today": [
                {"company": a.get("company"), "result": a["result"], "reason": a.get("reason")}
                for a in failed
            ],
            "halted_today": bool(failed),
            "approved_not_sent": len(pending),
            "awaiting_approval": len(awaiting),
            "inbound_today": inbound[0][0] if inbound else 0,
            "detail_reads_today": reads[0][0] if reads else 0,
            "snapshot": {
                "captured_at": snap["captured_at"] if snap else None,
                "conversations": len(snap["items"]) if snap else 0,
            },
            "pulled_without_greeting": [
                {"recruiter": i.get("recruiter", ""), "company": i.get("company", "")}
                for i in pulled
            ],
            "percent": round(100 * (sent + len(failed)) / total) if total else None,
        }
    con.close()
    return {"as_of": now.astimezone(PLATFORM_DAY).isoformat(), "boards": boards}


def pending_approvals(database: Path) -> list[dict[str, Any]]:
    """Questions put to the person that have no answer yet, word for word."""
    con = _connect(database)
    approvals = [
        json.loads(r[0]) for r in _rows(con, "SELECT approval_json FROM outreach_approvals")
    ]
    answered = {ap["batch_id"] for ap in approvals}
    batches = {
        r[0]: json.loads(r[1])
        for r in _rows(con, "SELECT batch_id, batch_json FROM outreach_batches")
    }
    # A job already greeted, or approved in another batch, makes an older question moot.
    settled = {
        json.loads(r[0])["job_id"]
        for r in _rows(con, "SELECT audit_json FROM outreach_audits")
        if json.loads(r[0])["result"] in ("sent", "duplicate_found")
    }
    for ap in approvals:
        items = batches.get(ap["batch_id"], {}).get("items", [])
        settled |= {i["job_id"] for i in items if i["number"] in ap["approved_numbers"]}
    withdrawn = {r[0] for r in _rows(con, "SELECT batch_id FROM outreach_withdrawals")}
    pending = []
    for batch_id, body in _rows(con, "SELECT batch_id, ask_json FROM outreach_asks"):
        if batch_id in answered or batch_id in withdrawn:
            continue
        jobs = {i["job_id"] for i in batches.get(batch_id, {}).get("items", [])}
        if jobs and jobs <= settled:
            continue
        ask = json.loads(body)
        pending.append(
            {
                "ask_id": ask["ask_id"],
                "batch_id": batch_id,
                "asked_at": ask.get("asked_at"),
                "question": ask["question"],
            }
        )
    con.close()
    return sorted(pending, key=lambda p: p["asked_at"] or "", reverse=True)


def patrol_history(database: Path, limit: int = 10) -> list[dict[str, Any]]:
    """Recent patrol checks: start, finish, and whether one was cut off."""
    con = _connect(database)
    rows = _rows(
        con,
        "SELECT c.check_id, c.checked_at, f.finished_at, c.check_json FROM patrol_checks c "
        "LEFT JOIN patrol_finishes f ON f.check_id = c.check_id "
        "ORDER BY c.checked_at DESC LIMIT ?",
        limit,
    )
    history = []
    for index, (check_id, started, finished, body) in enumerate(rows):
        snaps = _rows(
            con,
            "SELECT platform, count(*) FROM patrol_snapshots "
            "WHERE json_extract(snapshot_json, '$.check_id') = ? GROUP BY platform",
            check_id,
        )
        state = "finished" if finished else ("running_or_cut_off" if index == 0 else "cut_off")
        history.append(
            {
                "check_id": check_id,
                "started_at": started,
                "finished_at": finished,
                "state": state,
                "mode": json.loads(body).get("mode"),
                "snapshots": {platform: n for platform, n in snaps},
            }
        )
    con.close()
    return history


def new_jobs(database: Path, hours: int = 24, now: datetime | None = None) -> list[dict[str, Any]]:
    """Postings stored in the last hours, with their latest match decision."""
    now = now or datetime.now(UTC)
    since = (now - timedelta(hours=hours)).isoformat()
    con = _connect(database)
    jobs = []
    for job_id, source, collected in _rows(
        con,
        "SELECT job_id, source, collected_at FROM job_provenance WHERE collected_at >= ? "
        "ORDER BY collected_at DESC",
        since,
    ):
        job_row = _rows(con, "SELECT job_json FROM normalized_jobs WHERE job_id = ?", job_id)
        if not job_row:
            continue
        job = json.loads(job_row[0][0])
        match = _rows(
            con,
            "SELECT result_json FROM job_matches WHERE job_id = ? ORDER BY updated_at DESC LIMIT 1",
            job_id,
        )
        jobs.append(
            {
                "job_id": job_id,
                "source": source,
                "collected_at": collected,
                "company": job.get("company"),
                "title": job.get("title"),
                "location": job.get("location"),
                "url": job.get("url"),
                "match": json.loads(match[0][0])["decision"] if match else None,
            }
        )
    con.close()
    return jobs
