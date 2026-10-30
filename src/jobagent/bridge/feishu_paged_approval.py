# ruff: noqa: RUF001
"""Native per-job decisions, reusing the outreach service for all approvals."""

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jobagent.bridge import feishu_paged_card
from jobagent.bridge.greeting_freshness import verify_greeting_sources
from jobagent.errors import JobAgentError
from jobagent.outreach.service import OutreachService, contacted_job_ids, policy_digest
from jobagent.schemas.jobs import MatchResult
from jobagent.schemas.outreach import OutreachApproval, OutreachAsk, OutreachBatch, OutreachDraft
from jobagent.schemas.sourcing_feedback import JobDecisionDetail, PagedCardState, SourcingFeedback
from jobagent.storage.candidate_repository import SqliteCandidateRepository
from jobagent.storage.database import Database
from jobagent.storage.feedback_repository import SqliteFeedbackRepository
from jobagent.storage.job_repository import SqliteJobRepository
from jobagent.storage.outreach_repository import SqliteOutreachRepository

if TYPE_CHECKING:
    from jobagent.bridge.feishu_approval import CardOutcome


def load_state(database: Path, message_id: str) -> PagedCardState | None:
    db = Database(database)
    db.migrate()
    return SqliteFeedbackRepository(db).state(message_id)


def register_paged_card(
    database: Path, message_id: str, *, ask_id: str, batch_id: str,
    candidate_id: str | None = None, query_strategy_version: str = "unversioned",
    demo_mode: bool = False,
) -> None:
    db = Database(database)
    db.migrate()
    store = SqliteOutreachRepository(db)
    batch, ask = store.get_batch(batch_id), store.get_ask(ask_id)
    if (batch is None or ask is None or ask.batch_id != batch.batch_id
            or ask.batch_digest != batch.batch_digest or ask.policy_digest != batch.policy_digest
            or store.is_withdrawn(batch_id) or store.get_approval(batch_id)):
        raise ValueError("The card must reference a stored, matching question.")
    state = PagedCardState(
        message_id=message_id, batch_id=batch_id, ask_id=ask_id, candidate_id=candidate_id,
        query_strategy_version=query_strategy_version,
        expires_at=ask.asked_at + timedelta(hours=24),
        demo_mode=demo_mode,
    )
    SqliteFeedbackRepository(db).register(state)


def _details(
    database: Path, batch: OutreachBatch, state: PagedCardState,
) -> dict[str, JobDecisionDetail]:
    from jobagent.bridge.feishu_approval import card_details

    db = Database(database)
    jobs = SqliteJobRepository(db)
    old = card_details(database, batch)
    details = {}
    for item in batch.items:
        job = jobs.get_job(item.job_id)
        salary = None
        if job is not None and job.salary is not None:
            money = job.salary
            low = money.minimum if money.minimum is not None else "?"
            high = money.maximum if money.maximum is not None else "?"
            salary = (f"{low}–{high} "
                      f"{money.currency}/{money.period or '未提供周期'}")
        match, match_version = None, None
        if state.candidate_id:
            with db.connect() as connection:
                row = connection.execute(
                    "SELECT result_json, updated_at FROM job_matches "
                    "WHERE candidate_id = ? AND job_id = ? ORDER BY updated_at DESC LIMIT 1",
                    (state.candidate_id, item.job_id),
                ).fetchone()
            if row:
                match, match_version = MatchResult.model_validate_json(row[0]), str(row[1])
        detail = old.get(item.job_id)
        details[item.job_id] = JobDecisionDetail(
            location=job.location if job else None, salary_text=salary,
            points=detail.points if detail else [],
            match_score=match.overall if match else None, match_version=match_version,
            match_tier=match.decision.value if match else None,
            strengths=match.strengths if match else [],
            gaps=[*match.hard_gaps, *match.partial_matches, *match.uncertainties] if match else [],
        )
    return details


def current_card(database: Path, message_id: str, *, notice: str = "") -> dict[str, Any]:
    state = load_state(database, message_id)
    if state is None:
        raise ValueError("Unknown paged card.")
    store = SqliteOutreachRepository(Database(database))
    batch, ask = store.get_batch(state.batch_id), store.get_ask(state.ask_id)
    if batch is None or ask is None:
        raise ValueError("Missing card batch or question.")
    return feishu_paged_card.approval_card(batch, ask, state, _details(database, batch, state),
                                         notice=notice)


def _approve_one(
    db: Database, batch: OutreachBatch, page: int, words: str, *, now: datetime,
    owner: str, event_id: str, message_id: str, candidate_id: str | None,
) -> tuple[OutreachBatch, OutreachAsk, OutreachApproval]:
    item = batch.items[page]
    jobs, store, service = SqliteJobRepository(db), SqliteOutreachRepository(db), OutreachService()
    job = jobs.get_job(item.job_id)
    if candidate_id is None:
        raise ValueError("缺少候选人标识，不能核验当前证据。")
    if words != item.text and (
        item.source_binding is not None or item.variant == "whole-message.v1"
    ):
        raise ValueError("AI 招呼修改后需要全文重新生成并完成独立复核，再提交审批。")
    verify_greeting_sources(db, [item], candidate_id=candidate_id)
    confirmed = {
        e.id for e in SqliteCandidateRepository(db).list_evidence(candidate_id)
        if e.user_confirmed
    } if candidate_id else set()
    drafts = [OutreachDraft(
        job_id=item.job_id, platform=item.platform, text=item.text,
        evidence_ids=item.evidence_ids, variant=item.variant,
        hook_requirement=item.hook_requirement,
        experiment_id=item.experiment_id, written_by=item.written_by,
        source_binding=item.source_binding,
    )]
    kwargs: dict[str, Any] = {
        "jobs": {item.job_id: job} if job else {},
        "already_contacted": contacted_job_ids(store.list_audits()),
        "confirmed_evidence_ids": confirmed,
        "policy": batch.policy, "created_at": now,
        "match_tiers": {item.job_id: item.match_tier}, "harness_version": batch.harness_version,
    }
    if candidate_id is not None:
        current_tiers = jobs.latest_match_tiers(candidate_id, [item.job_id])
        if item.job_id in current_tiers:
            kwargs["match_tiers"] = current_tiers
    original = service.build_batch(drafts, batch_id="OBATCH_VALIDATE", **kwargs)
    if (original.batch is None or original.batch.items[0].item_digest != item.item_digest
            or policy_digest(batch.policy) != batch.policy_digest):
        raise ValueError("岗位或原文已变化，须重新提交审批。")
    drafts[0] = drafts[0].model_copy(update={
        "text": words, "written_by": "person" if words != item.text else item.written_by,
    })
    child_id = "OBATCH_PAGE_" + hashlib.sha256(
        f"{batch.batch_id}:{item.number}:{words}".encode()
    ).hexdigest()[:20].upper()
    report = service.build_batch(drafts, batch_id=child_id, **kwargs)
    if report.batch is None:
        raise ValueError("招呼未通过规则：" + "、".join(report.rejected[0].reasons))
    child = report.batch
    ask = service.ask(child, asked_at=now)
    answer = (f"本人在飞书批准第 {item.number} 条最终原文：{words}"
              f"（{owner}；{event_id}；{message_id}）")
    approval = service.approve(child, ask=ask, numbers=[1], attestation=answer, approved_at=now)
    return child, ask, approval


def handle_event(database: Path, event: dict[str, Any], *, owner: str,
                 now: datetime | None = None) -> "CardOutcome":
    from jobagent.bridge.feishu_approval import CardOutcome

    moment = now or datetime.now(UTC)
    db = Database(database)
    feedback_store = SqliteFeedbackRepository(db)
    message_id, event_id = str(event.get("message_id") or ""), str(event.get("event_id") or "")
    state = feedback_store.state(message_id)
    if state is None:
        return CardOutcome("ignored")
    if event.get("operator_id") != owner:
        return CardOutcome("rejected", ["只认本人的操作，没有登记。"])
    if event.get("action_tag") != "button":
        return CardOutcome("ignored")
    if not event_id:
        return CardOutcome("rejected", ["缺少事件标识，无法安全登记。"])
    if feedback_store.event_seen(event_id):
        return CardOutcome("duplicate")
    if state.closed or moment >= state.expires_at:
        return CardOutcome("rejected", ["卡片已处理完毕或过期，请重新提问。"])
    store = SqliteOutreachRepository(db)
    batch, ask = store.get_batch(state.batch_id), store.get_ask(state.ask_id)
    if (batch is None or ask is None or ask.batch_id != batch.batch_id
            or ask.batch_digest != batch.batch_digest or ask.policy_digest != batch.policy_digest
            or moment < ask.asked_at or store.is_withdrawn(state.batch_id)
            or store.get_approval(state.batch_id)):
        return CardOutcome("rejected", ["当前问题已变化、已撤回或已批准，没有登记。"])
    action = re.fullmatch(r"(previous|next|approve|revise|decline)_(\d+)_(\d+)",
                          str(event.get("action_name") or ""))
    if not action or int(action[2]) != state.page or int(action[3]) != state.revision:
        return CardOutcome("rejected", ["旧页面操作已失效，请使用当前卡片。"])
    try:
        form = json.loads(event.get("form_value") or "{}")
        if not isinstance(form, dict):
            raise ValueError("表单格式有误。")
        item = batch.items[state.page]
        key = str(item.number)
        words = form.get("greeting", state.drafts.get(key, item.text))
        if not isinstance(words, str) or not words.strip() or len(words) > 1000:
            raise ValueError("招呼原文为空或超过输入上限。")
        revised = state.model_copy(deep=True)
        revised.revision += 1
        if key not in revised.decisions:
            revised.drafts[key] = words
            reason, note = form.get("reason") or "other", form.get("note") or ""
            if reason not in feishu_paged_card.REASONS or not isinstance(note, str):
                raise ValueError("反馈字段格式有误。")
            revised.feedback_drafts[key] = {"reason": reason, "note": note}
        decision, feedback, bundle = action[1], None, None
        outcome = CardOutcome("updated", ["草稿已保存。"])
        if decision in ("previous", "next"):
            revised.page = max(0, min(len(batch.items) - 1,
                                     state.page + (-1 if decision == "previous" else 1)))
        else:
            if key in state.decisions:
                raise ValueError("本条已有决定，不能重复处理。")
            if decision == "approve" and words != item.text:
                decision = "revise"
            if state.demo_mode:
                revised.decisions[key] = (
                    "approved" if decision == "approve" else
                    "revision_requested" if decision == "revise" else "declined"
                )
                outcome = CardOutcome("updated", ["演示决定已保存；没有发送授权或真实偏好更新。"])
            elif decision == "revise":
                if state.candidate_id is None:
                    raise ValueError("缺少候选人标识，不能保存本人的修改偏好。")
                revised.decisions[key] = "revision_requested"
                outcome = CardOutcome("revision_requested", [
                    "已接受 JD 并保存原稿与修订意见；待全文重新生成和独立复核，没有发送权。"
                ])
            elif decision == "approve":
                bundle = _approve_one(db, batch, state.page, words, now=moment, owner=owner,
                                      event_id=event_id, message_id=message_id,
                                      candidate_id=state.candidate_id)
                revised.decisions[key] = "approved"
                revised.approved_batches[key] = bundle[0].batch_id
                outcome = CardOutcome("registered", ["已批准本条最终全文，尚未发送。"],
                                      bundle[2].approval_id)
            else:
                revised.decisions[key] = "declined"
                outcome = CardOutcome("declined", ["本条已回绝，没有发送授权。"])
            with db.connect() as connection:
                row = connection.execute(
                    "SELECT search_term FROM job_search_hits WHERE job_id = ? AND source = ? "
                    "ORDER BY collected_at DESC LIMIT 1", (item.job_id, item.platform),
                ).fetchone()
            job = SqliteJobRepository(db).get_job(item.job_id)
            if not state.demo_mode and state.candidate_id is not None and job is None:
                raise ValueError("缺少当前完整 JD，无法保存反馈来源。")
            feedback = None if state.demo_mode else SourcingFeedback(
                event_id=event_id, job_id=item.job_id, source=item.platform,
                search_term=str(row[0]) if row else None,
                query_strategy_version=state.query_strategy_version,
                action="approve" if decision == "approve" else
                "revise" if decision == "revise" else "decline",
                reason_category=form.get("reason") or "other", free_text=form.get("note") or "",
                content_digest="sha256:" + hashlib.sha256(words.encode()).hexdigest(),
                actor_id=owner, occurred_at=moment, idempotency_key=event_id,
                candidate_id=state.candidate_id,
                original_text=item.text if state.candidate_id is not None else None,
                revised_text=words if decision == "revise" else None,
                jd_text=job.jd_raw if job and state.candidate_id is not None else None,
                job_title=job.title if job and state.candidate_id is not None else None,
                company=job.company if job and state.candidate_id is not None else None,
            )
            pending = [
                i for i, x in enumerate(batch.items) if str(x.number) not in revised.decisions
            ]
            revised.closed = not pending
            if pending:
                revised.page = pending[0]
        saved = feedback_store.commit(
            revised, expected_revision=state.revision, event_id=event_id, now=moment,
            feedback=feedback, approval_bundle=bundle, withdraw_parent=revised.closed,
        )
        if saved != "stored":
            return CardOutcome("duplicate" if saved == "duplicate" else "rejected",
                               ["卡片状态已更新，请使用最新页面。"])
        outcome.card = current_card(database, message_id, notice=" ".join(outcome.lines))
        return outcome
    except (ValueError, JobAgentError) as error:
        return CardOutcome("rejected", [str(error)])
