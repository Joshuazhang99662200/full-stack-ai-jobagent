# ruff: noqa: RUF001, E501  -- Chinese labels and inline HTML templates.
"""Local read-only patrol dashboard: per-board progress, refreshed every 30 seconds.

Run: python scripts/patrol_dashboard.py [--port 8765] [--database .jobagent/jobagent.sqlite3]
It only reads the local database and private sourcing files; it never touches a board.
"""

import argparse
import html
import json
import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SHANGHAI = timezone(timedelta(hours=8))
PLATFORMS = (("boss", "Boss"), ("liepin", "猎聘"), ("zhaopin", "智联"))
ROOT = Path(__file__).resolve().parents[1]


def _rows(con: sqlite3.Connection, sql: str, *args: object) -> list[tuple]:
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []


def collect(database: Path) -> dict:
    now = datetime.now(UTC)
    local = now.astimezone(SHANGHAI)
    day_start = datetime.combine(local.date(), datetime.min.time(), SHANGHAI).astimezone(UTC)
    since = day_start.isoformat()
    con = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    audits = [json.loads(r[0]) for r in _rows(con, "SELECT audit_json FROM outreach_audits")]
    batches = {
        r[0]: json.loads(r[1])
        for r in _rows(con, "SELECT batch_id, batch_json FROM outreach_batches")
    }
    approvals = [json.loads(r[0]) for r in _rows(con, "SELECT approval_json FROM outreach_approvals")]
    asked = {r[0] for r in _rows(con, "SELECT batch_id FROM outreach_asks")}
    done = {(a["batch_id"], a["number"]): a for a in audits}
    approved = {(ap["batch_id"], n) for ap in approvals for n in ap["approved_numbers"]}
    approved_batches = {ap["batch_id"] for ap in approvals}

    boards = {}
    for key, label in PLATFORMS:
        todays = [
            a for a in audits
            if a["platform"] == key and a["recorded_at"] >= since
        ]
        sent = sum(a["result"] == "sent" for a in todays)
        failed = [a for a in todays if a["result"] in ("failed", "intervention")]
        pending = [
            (bid, item) for bid, b in batches.items() for item in b["items"]
            if item["platform"] == key and (bid, item["number"]) in approved
            and (bid, item["number"]) not in done
        ]
        awaiting = [
            (bid, item) for bid, b in batches.items() for item in b["items"]
            if item["platform"] == key and bid in asked and bid not in approved_batches
            and b.get("created_at", "") >= (now - timedelta(days=2)).isoformat()
        ]
        inbound = _rows(
            con,
            "SELECT count(*) FROM conversation_events e JOIN conversations c "
            "ON c.conversation_id = e.conversation_id WHERE c.platform = ? AND e.kind = 'inbound' "
            "AND e.recorded_at >= ?",
            key, since,
        )
        reads = _rows(
            con,
            "SELECT count(*) FROM job_provenance WHERE source = ? AND collected_at >= ?",
            key, since,
        )
        snap = _rows(
            con,
            "SELECT snapshot_json FROM patrol_snapshots WHERE platform = ? "
            "ORDER BY captured_at DESC LIMIT 1",
            key,
        )
        pulled, snap_at, snap_size = [], None, 0
        if snap:
            s = json.loads(snap[0][0])
            snap_at = s["captured_at"]
            snap_size = len(s["items"])
            contacted = {
                item["company"]
                for b in batches.values() for item in b["items"] if item["platform"] == key
            }
            pulled = [
                i for i in s["items"]
                if i.get("last_from") == "system"
                and not any(i.get("company", "") and i["company"] in c for c in contacted)
            ]
        total = sent + len(failed) + len(pending)
        boards[key] = {
            "label": label,
            "sent": sent,
            "failed": failed,
            "pending": len(pending),
            "awaiting": len(awaiting),
            "inbound": inbound[0][0] if inbound else 0,
            "reads": reads[0][0] if reads else 0,
            "pulled": pulled,
            "snap_at": snap_at,
            "snap_size": snap_size,
            "percent": round(100 * (sent + len(failed)) / total) if total else None,
        }

    check = _rows(
        con,
        "SELECT c.check_id, c.checked_at, f.finished_at FROM patrol_checks c "
        "LEFT JOIN patrol_finishes f ON f.check_id = c.check_id ORDER BY c.checked_at DESC LIMIT 1",
    )
    con.close()
    hc_dir = ROOT / "candidate/private/sourcing" / f"hc_{local:%Y%m%d}"
    hc = None
    if hc_dir.is_dir():
        records = list(hc_dir.glob("rec_*.json"))
        combined = hc_dir / "boss_hc.json"
        if combined.exists():
            try:
                records_n = len(json.loads(combined.read_text(encoding="utf-8")))
            except ValueError:
                records_n = len(records)
        else:
            records_n = len(records)
        hc = {"read": records_n, "drafts": any(hc_dir.glob("drafts*.json"))}
    return {"now": local, "boards": boards, "check": check[0] if check else None, "hc": hc}


def _local(ts: str | None) -> str:
    if not ts:
        return "—"
    return datetime.fromisoformat(ts).astimezone(SHANGHAI).strftime("%m-%d %H:%M")


def render(data: dict, hc_total: int) -> str:
    cards = []
    for b in data["boards"].values():
        halted = bool(b["failed"])
        pct = b["percent"]
        bar = 0 if pct is None else pct
        color = "#c0392b" if halted else "#2f6fd6"
        badge = (
            '<span class="badge bad">今日已叫停</span>' if halted
            else (
                '<span class="badge idle">暂无待发</span>' if pct is None
                else f'<span class="pct">{pct}%</span>'
            )
        )
        pulled = "".join(
            f"<li>{html.escape(i.get('recruiter', ''))}｜{html.escape(i.get('company', ''))}</li>"
            for i in b["pulled"][:15]
        )
        reason = "".join(
            f"<div class='muted'>{html.escape((f.get('reason') or f['result'])[:40])}</div>"
            for f in b["failed"]
        )
        cards.append(f"""
<div class="card">
  <div class="head"><b>{b['label']}</b>{badge}</div>
  <div class="track"><div class="fill" style="width:{bar}%;background:{color}"></div></div>
  <div class="row"><span>发送队列</span><span>已发 {b['sent']} · 失败 {len(b['failed'])} · 待发 {b['pending']}</span></div>
  <div class="row"><span>待你审批</span><span>{b['awaiting']} 条</span></div>
  <div class="row"><span>今日新来信</span><span>{b['inbound']} 条</span></div>
  <div class="row"><span>今日详情读取</span><span>{b['reads']} / 50</span></div>
  <div class="row"><span>拉起未发招呼</span><span>{len(b['pulled'])} 个</span></div>
  <ul>{pulled}</ul>
  <div class="row"><span>消息页快照</span><span>{b['snap_size']} 个会话 · {_local(b['snap_at'])}</span></div>{reason}
</div>""")
    check = data["check"]
    if check:
        state = "进行中" if check[2] is None else "已完工"
        patrol = f"最近巡检 {_local(check[1])}（{state}）"
    else:
        patrol = "还没有巡检记录"
    hc = data["hc"]
    hc_line = ""
    if hc:
        hc_pct = round(100 * min(hc["read"], hc_total) / hc_total) if hc_total else 0
        hc_line = (
            f"<div class='card wide'><div class='head'><b>HC 起草（子代理）</b>"
            f"<span class='pct'>{hc_pct}%</span></div><div class='track'><div class='fill' "
            f"style='width:{hc_pct}%;background:#2f6fd6'></div></div><div class='row'><span>读 JD</span>"
            f"<span>{hc['read']} / {hc_total}</span></div><div class='row'><span>草稿与审批单</span>"
            f"<span>{'已生成' if hc['drafts'] else '未生成'}</span></div></div>"
        )
    return f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="30"><title>巡检看板</title>
<style>
body{{font-family:system-ui,-apple-system,"Microsoft YaHei",sans-serif;margin:24px;color:#1f1f1f;background:#fafaf8}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px}}
.card{{background:#fff;border:1px solid #e5e3dc;border-radius:12px;padding:14px 16px}}
.wide{{grid-column:1/-1}} .head{{display:flex;justify-content:space-between;align-items:baseline}}
.pct{{font-size:22px}} .track{{height:8px;background:#f0efe9;border-radius:4px;margin:10px 0}}
.fill{{height:8px;border-radius:4px}} .row{{display:flex;justify-content:space-between;font-size:13px;line-height:1.9;color:#555}}
.muted{{font-size:12px;color:#888}} ul{{margin:4px 0 6px 18px;padding:0;font-size:12px;color:#555}}
.badge{{font-size:12px;padding:2px 8px;border-radius:6px}} .bad{{background:#fbe9e7;color:#a8321f}} .idle{{background:#eef2f7;color:#41536b}}
</style></head><body>
<div class="muted" style="margin-bottom:10px">更新于 {data['now']:%m-%d %H:%M:%S} · 每 30 秒自动刷新 · {patrol}</div>
<div class="grid">{''.join(cards)}{hc_line}</div></body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--database", default=str(ROOT / ".jobagent/jobagent.sqlite3"))
    parser.add_argument("--hc-total", type=int, default=13)
    args = parser.parse_args()
    database = Path(args.database)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = render(collect(database), args.hc_total).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_: object) -> None:
            return

    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
