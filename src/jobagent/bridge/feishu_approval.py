# ruff: noqa: RUF001  -- Cards for the person are written in Chinese.
"""Turn a submitted Feishu approval card into an outreach approval, or refuse it.

The same discipline as the chat panel holds:

- Only the configured person's submission counts. The card must be one this
  machine sent for a question that is still open.
- A tick and a submit is the approval; there is no second round. Unchanged
  ticked items are approved on the original batch, with the submission recorded
  as the person's answer.
- Ticked items the person rewrote become a batch written by the person and are
  approved at once with the rewritten words quoted in the answer, because the
  person typed exactly those words into the card. The usual greeting rules
  still apply to them; a rewrite that fails them is reported, not approved.

Each card is answered once. A repeated delivery of the same event is ignored.
Sending to recruiters is untouched: approved items wait for the browser session
like any other approval.
"""

import json
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from jobagent.bridge import feishu_card
from jobagent.bridge.greeting_freshness import verify_greeting_sources
from jobagent.errors import ContractValidationError, JobAgentError
from jobagent.outreach.service import OutreachService, contacted_job_ids
from jobagent.schemas.outreach import OutreachAsk, OutreachBatch, OutreachDraft
from jobagent.storage.database import Database
from jobagent.storage.job_repository import SqliteJobRepository
from jobagent.storage.outreach_repository import SqliteOutreachRepository

REGISTRY = "feishu_cards.json"
# Requirements that say little about fit (degrees) are left off the card.
PAPER = {"本科", "硕士", "博士", "学历", "学位", "统招"}
PRIORITY_ORDER = {"must": 0, "preferred": 1, "context": 2, "uncertain": 3}
# Keywords that set a JD apart sit in its preferred and context lines more than
# in its must-haves, which tend to be the same everywhere.
KEYWORD_ORDER = {"preferred": 0, "context": 1, "must": 2, "uncertain": 3}
GENERIC = {"AI", "产品经理", "文档", "工程师", "技术背景", "沟通", "逻辑", "经验"}
MUST_POINTS = 2
POINT_LIMIT = 4
POINT_LENGTH = 70
KEYWORD_LIMIT = 10

Updater = Callable[[str, dict[str, Any]], None]
CardSender = Callable[[dict[str, Any]], str]


@dataclass
class CardOutcome:
    status: str  # registered | rejected | duplicate | ignored
    lines: list[str] = field(default_factory=list)
    approval_id: str | None = None
    card: dict[str, Any] | None = None


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
    if any(item.source_binding is not None or item.variant == "whole-message.v1"
           for item in items):
        raise ContractValidationError(
            "AI 招呼修改后需要全文重新生成并完成独立复核，再提交审批。"
        )
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
            source_binding=item.source_binding,
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
    from jobagent.bridge.feishu_paged_approval import handle_event, load_state

    if load_state(database, str(event.get("message_id") or "")) is not None:
        return handle_event(database, event, owner=owner, now=now)
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

    outcome = CardOutcome("rejected")
    plain = [n for n in submission.chosen if n not in submission.edited]
    source = f"操作人 {owner}，事件 {event_id or '无'}，卡片 {event.get('message_id')}"
    try:
        chosen_items = [item for item in batch.items if item.number in submission.chosen]
        if any(item.number in submission.edited and (
            item.source_binding is not None or item.variant == "whole-message.v1"
        ) for item in chosen_items):
            return CardOutcome("rejected", [
                "AI 招呼修改后需要全文重新生成并完成独立复核，再提交审批。"
            ])
        verify_greeting_sources(db, chosen_items)
        if plain:
            chosen = "、".join(map(str, plain))
            approval = OutreachService().approve(
                batch,
                ask=ask,
                numbers=plain,
                attestation=f"飞书卡片提交：发 {chosen}（{source}）",
                approved_at=now,
            )
            store.save_approval(approval)
            outcome.status, outcome.approval_id = "registered", approval.approval_id
            outcome.lines.append(f"已登记：发 {chosen}（{approval.approval_id}）")
        if submission.edited:
            new_batch, refused = _rewrite(db, batch, submission.edited, now)
            outcome.lines += refused
            if new_batch is not None:
                # The person typed these words into the card and ticked them; the
                # submission carries them exactly, so it answers the rewrite directly.
                store.save_batch(new_batch)
                new_ask = OutreachService().ask(new_batch, asked_at=now)
                store.save_ask(new_ask)
                words = "；".join(f"「{item.text}」" for item in new_batch.items)
                rewrite = OutreachService().approve(
                    new_batch,
                    ask=new_ask,
                    numbers=[item.number for item in new_batch.items],
                    attestation=f"飞书卡片提交，本人改写后发送：{words}（{source}）",
                    approved_at=now,
                )
                store.save_approval(rewrite)
                outcome.status = "registered"
                outcome.approval_id = outcome.approval_id or rewrite.approval_id
                kept = {item.job_id for item in new_batch.items}
                numbers = "、".join(
                    str(n) for n in sorted(submission.edited) if batch.items[n - 1].job_id in kept
                )
                outcome.lines.append(f"已登记：第 {numbers} 条按你改写的原文发送")
    except JobAgentError as error:
        return CardOutcome("rejected", [f"没有登记：{error.message}"])
    if outcome.status != "registered":
        outcome.lines.append("卡片仍可修改后重新提交。")
        return outcome
    registry = _load(database)
    registry["cards"][str(event.get("message_id"))]["closed"] = True
    _save(database, registry)
    return outcome


def outcome_card(outcome: CardOutcome) -> dict[str, Any]:
    if outcome.card is not None:
        return outcome.card
    titles = {"registered": "审批已登记", "rejected": "没有登记"}
    return feishu_card.result_card(
        titles.get(outcome.status, outcome.status),
        [*outcome.lines, "<font color='grey'>发送仍由本机浏览器会话按节奏执行。</font>"],
        ok=outcome.status != "rejected",
    )


def card_details(database: Path, batch: OutreachBatch) -> dict[str, feishu_card.JobDetail]:
    """Location, keywords and the JD's own words for each item, from what is stored."""
    jobs = SqliteJobRepository(Database(database))
    details = {}
    for item in batch.items:
        job = jobs.get_job(item.job_id)
        profile = jobs.get_requirements(item.job_id)
        wanted = [
            r for r in (profile.requirements if profile else [])
            if not set(r.keywords) & PAPER and not any(w in r.source_span for w in PAPER)
        ]
        wanted.sort(key=lambda r: PRIORITY_ORDER.get(r.priority, len(PRIORITY_ORDER)))
        ranked = sorted(wanted, key=lambda r: KEYWORD_ORDER.get(r.priority, len(KEYWORD_ORDER)))
        keywords = [
            k for k in dict.fromkeys(k for r in ranked for k in r.keywords) if k not in GENERIC
        ]
        musts = [r for r in wanted if r.priority == "must"]
        others = [r for r in wanted if r.priority != "must"]
        shown = musts[:MUST_POINTS] + others[: POINT_LIMIT - min(len(musts), MUST_POINTS)]
        shown += [r for r in musts[MUST_POINTS:] if len(shown) < POINT_LIMIT][
            : POINT_LIMIT - len(shown)
        ]
        details[item.job_id] = feishu_card.JobDetail(
            location=job.location if job else None,
            keywords=keywords[:KEYWORD_LIMIT],
            points=[_clip(r.source_span) for r in shown],
        )
    return details


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= POINT_LENGTH else text[: POINT_LENGTH - 1] + "…"


def send_question_card(
    database: Path, batch: OutreachBatch, ask: OutreachAsk, send_card: CardSender,
    *, candidate_id: str | None = None, query_strategy_version: str = "unversioned",
    demo_mode: bool = False,
) -> str:
    from jobagent.bridge.feishu_paged_approval import _details, register_paged_card
    from jobagent.bridge.feishu_paged_card import approval_card
    from jobagent.schemas.sourcing_feedback import PagedCardState

    state = PagedCardState(
        message_id="pending_send", batch_id=batch.batch_id, ask_id=ask.ask_id,
        expires_at=ask.asked_at + timedelta(hours=24), candidate_id=candidate_id,
        query_strategy_version=query_strategy_version,
        demo_mode=demo_mode,
    )
    message_id = send_card(approval_card(batch, ask, state, _details(database, batch, state)))
    register_card(database, message_id, ask_id=ask.ask_id, batch_id=batch.batch_id)
    register_paged_card(database, message_id, ask_id=ask.ask_id, batch_id=batch.batch_id,
                        candidate_id=candidate_id, query_strategy_version=query_strategy_version,
                        demo_mode=demo_mode)
    return message_id


def listen(
    lines: Iterable[str],
    database: Path,
    *,
    owner: str,
    update: Updater,
) -> list[CardOutcome]:
    """Handle each card event line and show the outcome on the card itself."""
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
    return outcomes
