# ruff: noqa: RUF001  -- Cards for the person are written in Chinese.
"""Turn a submitted Feishu approval card into an outreach approval, or refuse it.

The same discipline as the chat panel holds:

- Only the configured person's submission counts. The card must be one this
  machine sent for a question that is still open.
- Ticked items whose words are unchanged are approved on the original batch.
  The submission itself is recorded as the person's answer.
- Ticked items the person rewrote are not approved from this card. They become
  a new batch written by the person, a new question and a new card. Only the
  answer to that card approves them, so every approval still answers a question
  that showed the exact words.

Each card is answered once. A repeated delivery of the same event is ignored.
Sending to recruiters is untouched: approved items wait for the browser session
like any other approval.
"""

import json
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jobagent.bridge import feishu_card
from jobagent.errors import JobAgentError
from jobagent.outreach.service import OutreachService, contacted_job_ids
from jobagent.schemas.outreach import OutreachAsk, OutreachBatch, OutreachDraft
from jobagent.storage.database import Database
from jobagent.storage.job_repository import SqliteJobRepository
from jobagent.storage.outreach_repository import SqliteOutreachRepository

REGISTRY = "feishu_cards.json"

Updater = Callable[[str, dict[str, Any]], None]
CardSender = Callable[[dict[str, Any]], str]


@dataclass
class CardOutcome:
    status: str  # registered | confirm | rejected | duplicate | ignored
    lines: list[str] = field(default_factory=list)
    approval_id: str | None = None
    follow_up: tuple[OutreachBatch, OutreachAsk] | None = None


def _registry_path(database: Path) -> Path:
    return database.parent / REGISTRY


def _load(database: Path) -> dict[str, Any]:
    path = _registry_path(database)
    if not path.exists():
        return {"cards": {}, "events": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {"cards": {}, "events": []}
    return {"cards": raw.get("cards", {}), "events": raw.get("events", [])}


def _save(database: Path, registry: dict[str, Any]) -> None:
    registry["events"] = registry["events"][-500:]
    _registry_path(database).write_text(
        json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def register_card(database: Path, message_id: str, *, ask_id: str, batch_id: str) -> None:
    registry = _load(database)
    registry["cards"][message_id] = {
        "ask_id": ask_id,
        "batch_id": batch_id,
        "sent_at": datetime.now(UTC).isoformat(),
        "closed": False,
    }
    _save(database, registry)


def card_for(message_id: str, database: Path) -> dict[str, Any] | None:
    card: dict[str, Any] | None = _load(database)["cards"].get(message_id)
    return card


def carded_asks(database: Path) -> set[str]:
    return {card["ask_id"] for card in _load(database)["cards"].values()}


def _rewrite(
    db: Database, batch: OutreachBatch, edited: dict[int, str], now: datetime
) -> tuple[OutreachBatch | None, list[str]]:
    store = SqliteOutreachRepository(db)
    jobs = SqliteJobRepository(db)
    items = [item for item in batch.items if item.number in edited]
    drafts = [
        OutreachDraft(
            job_id=item.job_id,
            platform=item.platform,
            text=edited[item.number],
            evidence_ids=item.evidence_ids,
            variant=item.variant,
            hook_requirement=item.hook_requirement,
            experiment_id=item.experiment_id,
            written_by="person",
        )
        for item in items
    ]
    found = {item.job_id: jobs.get_job(item.job_id) for item in items}
    report = OutreachService().build_batch(
        drafts,
        jobs={job_id: job for job_id, job in found.items() if job is not None},
        already_contacted=contacted_job_ids(store.list_audits()),
        confirmed_evidence_ids={e for item in items for e in item.evidence_ids},
        batch_id=f"OBATCH_{uuid.uuid4().hex[:16].upper()}",
        created_at=now,
        policy=batch.policy,
        match_tiers={item.job_id: item.match_tier or "hand_picked" for item in items},
        harness_version=batch.harness_version,
    )
    refused = [
        f"改写未通过（{items[r.index].company}）：{'、'.join(r.reasons)}" for r in report.rejected
    ]
    return report.batch, refused


def handle_card_event(
    database: Path, event: dict[str, Any], *, owner: str, now: datetime | None = None
) -> CardOutcome:
    """Register what one card submission approves; never sends anything."""
    now = now or datetime.now(UTC)
    form_raw = event.get("form_value") or ""
    if event.get("action_tag") != "button" or not form_raw:
        return CardOutcome("ignored")
    registry = _load(database)
    event_id = str(event.get("event_id") or "")
    if event_id and event_id in registry["events"]:
        return CardOutcome("duplicate")
    if event_id:
        registry["events"].append(event_id)
        _save(database, registry)
    if event.get("operator_id") != owner:
        return CardOutcome("rejected", ["只认本人的提交，这次提交没有登记。"])
    card = registry["cards"].get(str(event.get("message_id")))
    if card is None:
        return CardOutcome("rejected", ["这张卡不是本机发出的审批卡，没有登记。"])
    if card["closed"]:
        return CardOutcome("rejected", ["这张卡已处理过，没有重复登记。"])
    db = Database(database)
    store = SqliteOutreachRepository(db)
    batch, ask = store.get_batch(card["batch_id"]), store.get_ask(card["ask_id"])
    if batch is None or ask is None:
        return CardOutcome("rejected", ["找不到这张卡对应的批次或问题，没有登记。"])
    if store.is_withdrawn(batch.batch_id) or store.get_approval(batch.batch_id) is not None:
        return CardOutcome("rejected", ["这批已经撤回或登记过，没有重复登记。"])
    try:
        form = json.loads(form_raw)
    except ValueError:
        return CardOutcome("rejected", ["提交内容读不出来，没有登记。"])
    submission = feishu_card.read_submission(form if isinstance(form, dict) else {}, batch)
    if not submission.chosen:
        return CardOutcome("rejected", ["没有勾选任何条目，卡片仍可重新提交。"])

    outcome = CardOutcome("confirm")
    plain = [n for n in submission.chosen if n not in submission.edited]
    try:
        if plain:
            approval = OutreachService().approve(
                batch,
                ask=ask,
                numbers=plain,
                attestation=(
                    f"飞书卡片提交：发 {'、'.join(map(str, plain))}"
                    f"（操作人 {owner}，事件 {event_id or '无'}，卡片 {event.get('message_id')}）"
                ),
                approved_at=now,
            )
            store.save_approval(approval)
            outcome.status, outcome.approval_id = "registered", approval.approval_id
            chosen = "、".join(map(str, plain))
            outcome.lines.append(f"已登记：发 {chosen}（{approval.approval_id}）")
        if submission.edited:
            new_batch, refused = _rewrite(db, batch, submission.edited, now)
            outcome.lines += refused
            if new_batch is not None:
                store.save_batch(new_batch)
                new_ask = OutreachService().ask(new_batch, asked_at=now)
                store.save_ask(new_ask)
                outcome.follow_up = (new_batch, new_ask)
                numbers = "、".join(map(str, sorted(submission.edited)))
                outcome.lines.append(f"第 {numbers} 条改写过，已另发确认卡，确认后才登记。")
    except JobAgentError as error:
        return CardOutcome("rejected", [f"没有登记：{error.message}"])
    if outcome.status == "confirm" and outcome.follow_up is None:
        outcome.status = "rejected"
    registry = _load(database)
    registry["cards"][str(event.get("message_id"))]["closed"] = True
    _save(database, registry)
    return outcome


def outcome_card(outcome: CardOutcome) -> dict[str, Any]:
    titles = {"registered": "审批已登记", "confirm": "改写待确认", "rejected": "没有登记"}
    return feishu_card.result_card(
        titles.get(outcome.status, outcome.status),
        [*outcome.lines, "<font color='grey'>发送仍由本机浏览器会话按节奏执行。</font>"],
        ok=outcome.status != "rejected",
    )


def send_question_card(
    database: Path, batch: OutreachBatch, ask: OutreachAsk, send_card: CardSender
) -> str:
    message_id = send_card(feishu_card.approval_card(batch, ask))
    register_card(database, message_id, ask_id=ask.ask_id, batch_id=batch.batch_id)
    return message_id


def listen(
    lines: Iterable[str],
    database: Path,
    *,
    owner: str,
    update: Updater,
    send_card: CardSender,
) -> list[CardOutcome]:
    """Handle each card event line; update the card and send any follow-up question."""
    outcomes = []
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        outcome = handle_card_event(database, event, owner=owner)
        if outcome.status in ("ignored", "duplicate"):
            continue
        outcomes.append(outcome)
        token = event.get("token")
        if token:
            update(str(token), outcome_card(outcome))
        if outcome.follow_up is not None:
            send_question_card(database, *outcome.follow_up, send_card)
    return outcomes
