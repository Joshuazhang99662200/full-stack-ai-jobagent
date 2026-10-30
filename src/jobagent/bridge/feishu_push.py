# ruff: noqa: RUF001  -- Messages to the person are written in Chinese.
"""Push what changed in the local ledger to the person's phone through a Feishu bot.

Each push reads the ledger, keys every item that is worth a look (an unanswered
question, a recruiter's new message, a newly matched posting, a halted board)
and sends one message through `lark-cli` for the keys not pushed before. A key
is remembered only after the send succeeds, so a failure is retried next time
and a rerun never repeats itself. A finished patrol rides along but never
triggers a push on its own.

This only informs. It approves nothing and sends nothing to recruiters: an
answer still has to come back through the chat and be registered with
`outreach approve`.

Both files sit next to the SQLite database, which never enters git:

- feishu_push.json        one recipient: {"chat_id": "oc_..."} or {"user_id": "ou_..."} for an
                          app bot sent through lark-cli (optional "binary", "profile"), or
                          {"webhook": "https://...", "secret": "..."} for a group's custom bot,
                          which needs no app and no verified organisation
- feishu_push_state.json  the keys already pushed
"""

import base64
import hashlib
import hmac
import json
import re
import shutil
import sqlite3
import subprocess
import time
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from jobagent.bridge import feishu_approval, status
from jobagent.outreach.service import PLATFORM_DAY
from jobagent.storage.database import Database
from jobagent.storage.outreach_repository import SqliteOutreachRepository

CONFIG = "feishu_push.json"
STATE = "feishu_push_state.json"
PROMISING = ("strong_match", "possible_match")
JOB_LIMIT = 25
REPORT_LIMIT = 6000
# A background listener must not flash a console window per lark-cli call.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
LABELS = dict(status.PLATFORMS)

Sender = Callable[[str, str], None]


class PushError(Exception):
    """The push could not be configured or sent."""


@dataclass(frozen=True)
class Update:
    key: str
    section: str
    text: str
    quiet: bool = False


@dataclass(frozen=True)
class PushConfig:
    chat_id: str | None = None
    user_id: str | None = None
    binary: str | None = None
    webhook: str | None = None
    secret: str | None = None
    profile: str | None = None
    # Whose card submissions count; defaults to user_id.
    owner: str | None = None
    # Explicit knowledge-base identity; never inferred from recipient or old evidence.
    candidate_id: str | None = None


def load_config(path: Path) -> PushConfig:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PushError(f"{path.name} is not readable JSON: {error}") from None
    config = PushConfig(
        raw.get("chat_id"), raw.get("user_id"), raw.get("binary"),
        raw.get("webhook"), raw.get("secret"), raw.get("profile"),
        raw.get("owner"),
        raw.get("candidate_id"),
    )
    if sum(bool(t) for t in (config.chat_id, config.user_id, config.webhook)) != 1:
        raise PushError(f"{path.name} needs exactly one of chat_id, user_id or webhook.")
    if config.webhook and not config.webhook.startswith("https://"):
        raise PushError(f"{path.name}: webhook must be an https URL.")
    if config.candidate_id is not None and (
        not isinstance(config.candidate_id, str)
        or re.fullmatch(r"CAND_[A-Z0-9_]+", config.candidate_id) is None
    ):
        raise PushError(f"{path.name}: candidate_id must be an explicit CAND_* identifier.")
    return config


def _local(moment: str | None) -> str:
    if not moment:
        return ""
    return datetime.fromisoformat(moment).astimezone(PLATFORM_DAY).strftime("%m-%d %H:%M")


def _inbound(database: Path, since: str) -> list[Update]:
    con = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT e.event_id, e.event_json, c.platform, c.conversation_json "
            "FROM conversation_events e JOIN conversations c "
            "ON c.conversation_id = e.conversation_id "
            "WHERE e.kind = 'inbound' AND e.recorded_at >= ? ORDER BY e.recorded_at",
            (since,),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        con.close()
    updates = []
    for event_id, event_json, platform, conversation_json in rows:
        message = json.loads(event_json).get("inbound") or {}
        talk = json.loads(conversation_json)
        where = "｜".join(
            part for part in (LABELS.get(platform, platform), talk.get("company"),
                              talk.get("title")) if part
        )
        text = f"- {where}：「{message.get('text', '')}」"
        updates.append(Update(f"inbound:{event_id}", "招聘方新来信", text))
    return updates


def collect(database: Path, now: datetime | None = None, *, cards: bool = False) -> list[Update]:
    """Everything currently worth a push, keyed so a repeat can be recognised."""
    now = now or datetime.now(UTC)
    updates = [
        Update(f"patrol:{p['check_id']}", "巡检", f"巡检 {_local(p['finished_at'])} 完成", True)
        for p in status.patrol_history(database, limit=5)
        if p["state"] == "finished"
    ]
    for ask in status.pending_approvals(database):
        batch = ask["batch_id"]
        updates.append(
            Update(
                f"ask:{ask['ask_id']}",
                "待审批",
                f"**{batch}**：审批卡片见下一条消息（勾选、可改原文，点提交审批）"
                if cards
                else f"**{batch}**（回到对话回复「审批 {batch}：发 1、3」）\n{ask['question']}",
            )
        )
    updates += _inbound(database, (now - timedelta(days=2)).isoformat())
    for job in status.new_jobs(database, hours=24, now=now):
        if job["match"] in PROMISING:
            line = "｜".join(
                str(part) for part in (job["source"], job["company"], job["title"],
                                       job["location"], job["match"]) if part
            )
            updates.append(Update(f"job:{job['job_id']}", "新职位·强/可能匹配", f"- {line}"))
    day = now.astimezone(PLATFORM_DAY).date().isoformat()
    for key, board in status.status_today(database, now)["boards"].items():
        if board["halted_today"]:
            reasons = "；".join(
                f"{f['company'] or ''} {f['result']} {f['reason'] or ''}".strip()
                for f in board["failed_today"]
            )
            updates.append(Update(f"halt:{key}:{day}", "已叫停", f"- {board['label']}：{reasons}"))
    return updates


def render(updates: list[Update], now: datetime) -> str:
    lines = [f"**求职助手推送** {now.astimezone(PLATFORM_DAY):%m-%d %H:%M}"]
    lines += [u.text for u in updates if u.section == "巡检"]
    sections: dict[str, list[Update]] = {}
    for update in updates:
        if update.section != "巡检":
            sections.setdefault(update.section, []).append(update)
    for section, items in sections.items():
        counted = section if section == "巡检汇报" else f"{section}（{len(items)}）"
        lines += ["", f"**{counted}**"]
        shown = items[:JOB_LIMIT] if section.startswith("新职位") else items
        lines += [u.text for u in shown]
        if len(shown) < len(items):
            lines.append(f"另有 {len(items) - len(shown)} 条，见本机看板")
    return "\n".join(lines)


def _read_state(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        sent = json.loads(path.read_text(encoding="utf-8")).get("sent", {})
    except ValueError:
        return {}
    return sent if isinstance(sent, dict) else {}


def push(
    database: Path,
    *,
    send: Sender,
    now: datetime | None = None,
    dry_run: bool = False,
    cards: bool = False,
    extra: Sequence[Update] = (),
) -> dict[str, Any]:
    """Send one message when anything not pushed before is worth a look."""
    now = now or datetime.now(UTC)
    state_path = database.parent / STATE
    pushed = _read_state(state_path)
    updates = [*extra, *collect(database, now, cards=cards)]
    fresh = [u for u in updates if u.key not in pushed]
    keys = [u.key for u in fresh]
    if not any(not u.quiet for u in fresh):
        return {"sent": False, "reason": "no_update", "keys": [], "markdown": ""}
    markdown = render(fresh, now)
    if dry_run:
        return {"sent": False, "reason": "dry_run", "keys": keys, "markdown": markdown}
    digest = hashlib.sha256("\n".join(sorted(keys)).encode("utf-8")).hexdigest()
    send(markdown, f"jobagent-{digest[:40]}")
    pushed.update(dict.fromkeys(keys, now.isoformat()))
    state_path.write_text(
        json.dumps({"sent": pushed}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"sent": True, "keys": keys, "markdown": markdown}


def _binary(config: PushConfig) -> str:
    if config.binary:
        return config.binary
    found = shutil.which("lark-cli")
    if found is None:
        raise PushError("lark-cli is not on PATH; set binary in feishu_push.json.")
    # The npm shim goes through cmd.exe, which mangles newlines; call the real binary.
    real = Path(found).parent / "node_modules/@larksuite/cli/bin/lark-cli.exe"
    return str(real) if real.exists() else found


def _lark(config: PushConfig, *args: str) -> list[str]:
    profile = ["--profile", config.profile] if config.profile else []
    return [_binary(config), *profile, *args]


def _target(config: PushConfig) -> list[str]:
    return ["--chat-id", config.chat_id] if config.chat_id else ["--user-id", str(config.user_id)]


def lark_command(config: PushConfig, markdown: str, key: str) -> list[str]:
    return _lark(
        config, "im", "+messages-send", "--as", "bot", *_target(config),
        "--markdown", markdown, "--idempotency-key", key,
    )


def card_command(config: PushConfig, card: dict[str, Any]) -> list[str]:
    return _lark(
        config, "im", "+messages-send", "--as", "bot", *_target(config),
        "--msg-type", "interactive", "--content", json.dumps(card, ensure_ascii=False),
    )


def update_command(config: PushConfig, token: str, card: dict[str, Any]) -> list[str]:
    data = json.dumps({"token": token, "card": card}, ensure_ascii=False)
    return _lark(
        config, "api", "POST", "/open-apis/interactive/v1/card/update", "--as", "bot",
        "--data", data,
    )


def listen_command(config: PushConfig, *, hours: int) -> list[str]:
    return _lark(config, "event", "consume", "card.action.trigger", "--as", "bot",
                 "--timeout", f"{hours}h")


def run_lark(command: list[str]) -> dict[str, Any]:
    try:
        done = subprocess.run(
            command, capture_output=True, timeout=60, check=False, creationflags=NO_WINDOW
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PushError(f"lark-cli could not run: {error}") from None
    output = done.stdout.decode("utf-8", errors="replace")
    if done.returncode != 0 or '"ok": false' in output:
        detail = (output or done.stderr.decode("utf-8", errors="replace"))[-500:]
        raise PushError(f"lark-cli exited {done.returncode}: {detail}")
    try:
        reply = json.loads(output)
    except ValueError:
        return {}
    return reply if isinstance(reply, dict) else {}


def lark_sender(config: PushConfig) -> Sender:
    def send(markdown: str, key: str) -> None:
        run_lark(lark_command(config, markdown, key))

    return send


def lark_card_sender(config: PushConfig) -> Callable[[dict[str, Any]], str]:
    def send_card(card: dict[str, Any]) -> str:
        message_id = (run_lark(card_command(config, card)).get("data") or {}).get("message_id")
        if not message_id:
            raise PushError("lark-cli sent the card but returned no message_id.")
        return str(message_id)

    return send_card


def lark_card_updater(config: PushConfig) -> Callable[[str, dict[str, Any]], None]:
    def update(token: str, card: dict[str, Any]) -> None:
        run_lark(update_command(config, token, card))

    return update


def send_cards(
    database: Path, send_card: Callable[[dict[str, Any]], str], *, candidate_id: str | None = None,
) -> list[str]:
    """One approval card for every open question that has none yet."""
    store = SqliteOutreachRepository(Database(database))
    done = feishu_approval.carded_asks(database)
    sent = []
    for pending in status.pending_approvals(database):
        if pending["ask_id"] in done:
            continue
        batch, ask = store.get_batch(pending["batch_id"]), store.get_ask(pending["ask_id"])
        if batch is not None and ask is not None:
            sent.append(feishu_approval.send_question_card(
                database, batch, ask, send_card, candidate_id=candidate_id,
            ))
    return sent


def webhook_payload(
    config: PushConfig, markdown: str, timestamp: int | None = None
) -> dict[str, Any]:
    """A custom bot card; signed when the bot has a signing secret."""
    payload: dict[str, Any] = {
        "msg_type": "interactive",
        "card": {"elements": [{"tag": "markdown", "content": markdown}]},
    }
    if config.secret:
        stamp = str(timestamp if timestamp is not None else int(time.time()))
        key = f"{stamp}\n{config.secret}".encode()
        digest = hmac.new(key, digestmod=hashlib.sha256).digest()
        payload |= {"timestamp": stamp, "sign": base64.b64encode(digest).decode()}
    return payload


def webhook_sender(config: PushConfig) -> Sender:
    def send(markdown: str, _key: str) -> None:
        body = json.dumps(webhook_payload(config, markdown), ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            str(config.webhook), data=body, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                reply = json.loads(response.read().decode("utf-8") or "{}")
        except (OSError, ValueError) as error:
            raise PushError(f"webhook could not be reached: {error}") from None
        if reply.get("code", reply.get("StatusCode", 0)) != 0:
            raise PushError(f"webhook refused the message: {reply.get('msg', reply)}")

    return send


def sender_for(config: PushConfig) -> Sender:
    return webhook_sender(config) if config.webhook else lark_sender(config)


def report_update(check_id: str, text: str) -> Update:
    """A patrol's own report, pushed word for word (cut at REPORT_LIMIT characters)."""
    body = text.strip()
    if len(body) > REPORT_LIMIT:
        body = body[:REPORT_LIMIT] + "\n……（汇报过长，余下见本机）"
    return Update(f"report:{check_id}", "巡检汇报", body)


def auto_push(
    database: Path, now: datetime | None = None, extra: Sequence[Update] = ()
) -> dict[str, Any] | None:
    """Push after a state change when a recipient is configured; never raises."""
    path = database.parent / CONFIG
    if not path.exists():
        return None
    try:
        config = load_config(path)
        cards = not config.webhook
        report = push(database, send=sender_for(config), now=now, cards=cards, extra=extra)
        carded = send_cards(
            database, lark_card_sender(config), candidate_id=config.candidate_id,
        ) if cards else []
    except PushError as error:
        return {"sent": False, "error": str(error)}
    return {"sent": report["sent"], "keys": len(report["keys"]), "cards": len(carded)}
