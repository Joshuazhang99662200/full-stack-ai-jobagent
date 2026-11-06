# ruff: noqa: RUF001  -- user-facing receipts are written in Chinese.
"""Per-item greeting decisions from a host panel (such as Muse), through existing gates.

The panel is only a front end. A decision names the candidate, the pipeline
contact, the exact material revision (the asked item's digest) and the exact
words. Approval reuses the outreach approval gate on a single-item list built
from the asked item, so it is bound to the same digests as any other approval;
edited words are never approved directly. Declines and revisions become owner
feedback. Nothing here sends, and every outcome can be read back by its key.
"""

from datetime import datetime
from pathlib import Path

from jobagent.bridge.greeting_freshness import verify_greeting_sources
from jobagent.digest import canonical_digest, text_digest
from jobagent.errors import JobAgentError
from jobagent.outreach.service import OutreachService, contacted_job_ids, policy_digest
from jobagent.schemas.console_host import HostDecisionRequest, HostMaterial, HostReceipt
from jobagent.schemas.outreach import (
    OutreachApproval,
    OutreachAsk,
    OutreachBatch,
    OutreachDraft,
    OutreachItem,
)
from jobagent.schemas.sourcing_feedback import PagedCardState, SourcingFeedback
from jobagent.storage.candidate_repository import SqliteCandidateRepository
from jobagent.storage.database import Database
from jobagent.storage.feedback_repository import SqliteFeedbackRepository
from jobagent.storage.job_repository import SqliteJobRepository
from jobagent.storage.outreach_repository import SqliteOutreachRepository
from jobagent.storage.pipeline_repository import PipelineRepository

CHANNEL = "Muse 面板"
_ACTIONS = {"approve_text": "approve", "save_draft": "revise", "decline": "decline"}
_DECIDED = {"approve": "approved", "revise": "revision_requested", "decline": "declined"}


class _Rejected(Exception):
    pass


def _event_id(candidate_id: str, operation_key: str) -> str:
    return "PANEL_" + canonical_digest([candidate_id, operation_key])[7:31].upper()


def _state_id(ask_id: str) -> str:
    return "PANEL_" + ask_id


def _owned(db: Database, candidate_id: str) -> set[str]:
    return {
        e.id for e in SqliteCandidateRepository(db).list_evidence(candidate_id)
        if e.user_confirmed and e.confidence.value != "weak"
    }


def _normalized_job_id(db: Database, candidate_id: str, contact_id: str) -> tuple[str, str]:
    try:
        job, meta = PipelineRepository(db).get(contact_id, candidate_id)
    except JobAgentError:
        raise _Rejected("这个岗位不属于当前候选人。") from None
    if meta.normalized_job_id is None:
        raise _Rejected("这个岗位尚未关联已保存的职位。")
    return job.job_id, meta.normalized_job_id


def _open_items(
    db: Database, candidate_id: str, normalized_job_id: str
) -> list[tuple[OutreachBatch, OutreachAsk, OutreachItem]]:
    """Asked, unapproved, unwithdrawn items for this job that no decision has closed."""
    store, feedback = SqliteOutreachRepository(db), SqliteFeedbackRepository(db)
    owned = _owned(db, candidate_id)
    with db.connect() as connection:
        asks = [
            OutreachAsk.model_validate_json(row[0])
            for row in connection.execute("SELECT ask_json FROM outreach_asks")
        ]
    result = []
    for ask in sorted(asks, key=lambda a: a.asked_at, reverse=True):
        batch = store.get_batch(ask.batch_id)
        if (batch is None or ask.batch_digest != batch.batch_digest
                or store.get_approval(batch.batch_id) is not None
                or store.is_withdrawn(batch.batch_id)):
            continue
        state = feedback.state(_state_id(ask.ask_id))
        for item in batch.items:
            if (item.job_id == normalized_job_id and item.evidence_ids
                    and set(item.evidence_ids) <= owned
                    and (state is None or str(item.number) not in state.decisions)):
                result.append((batch, ask, item))
    return result


def panel_materials(database: Path, candidate_id: str, contact_id: str) -> list[HostMaterial]:
    """The exact greetings currently awaiting this person's decision for one contact."""
    db = Database(database)
    try:
        _, job_id = _normalized_job_id(db, candidate_id, contact_id)
    except _Rejected:
        return []
    return [
        HostMaterial(
            revision=item.item_digest, label=f"首条招呼（待你决定，清单第 {item.number} 条）",
            body=item.text, attachments=[],
        )
        for _, _, item in _open_items(db, candidate_id, job_id)
    ]


def _stored(db: Database, event_id: str) -> SourcingFeedback | None:
    with db.connect() as connection:
        row = connection.execute(
            "SELECT event_json FROM sourcing_feedback_events WHERE event_id = ?", (event_id,)
        ).fetchone()
    return None if row is None else SourcingFeedback.model_validate_json(row[0])


def panel_operation(database: Path, candidate_id: str, operation_key: str) -> HostReceipt:
    """Read back one panel operation; an absent record was never stored."""
    db = Database(database)
    event_id = _event_id(candidate_id, operation_key)
    event = _stored(db, event_id)
    if event is None or event.candidate_id != candidate_id:
        return HostReceipt(
            operation_key=operation_key, status="rejected",
            message="没有找到这次操作的保存记录，可以重新提交。",
        )
    return HostReceipt(
        operation_key=operation_key, status="saved", event_id=event_id,
        message=_MESSAGES[event.action],
    )


_MESSAGES = {
    "approve": "已批准这条招呼的准确全文，尚未发送。",
    "revise": "已保存你的修改意见，需要重新生成并复核后再审批，没有发送权。",
    "decline": "已记下不发这条，没有发送授权。",
}


def record_panel_decision(
    database: Path, request: HostDecisionRequest, *, actor_id: str, now: datetime
) -> HostReceipt:
    def rejected(message: str) -> HostReceipt:
        return HostReceipt(operation_key=request.operation_key, status="rejected", message=message)

    db = Database(database)
    db.migrate()
    action = _ACTIONS.get(request.kind)
    if action is None:
        return rejected("这个操作还没有接入面板保存，请在对话中处理。")
    if request.attachment_digests:
        return rejected("首条招呼不带附件；附件材料需走简历审批。")
    event_id = _event_id(request.candidate_id, request.operation_key)
    previous = _stored(db, event_id)
    if previous is not None:
        same = (previous.candidate_id == request.candidate_id and previous.action == action
                and previous.content_digest == text_digest(request.body))
        return panel_operation(database, request.candidate_id, request.operation_key) if same \
            else rejected("同一操作键已保存了不同的决定，已停止写入。")
    try:
        platform_job, job_id = _normalized_job_id(db, request.candidate_id, request.contact_id)
        if platform_job != request.job_id:
            raise _Rejected("岗位与面板联系记录不一致。")
        matches = [
            entry for entry in _open_items(db, request.candidate_id, job_id)
            if entry[2].item_digest == request.material_revision
        ]
        if not matches:
            raise _Rejected("这条招呼已变化、已处理或已撤回，请刷新后查看最新版本。")
        batch, ask, item = matches[0]
        if action == "approve" and request.body != item.text:
            raise _Rejected("修改后的文字不能直接批准；请先保存修改，重新生成并复核后再审批。")
        if action == "revise" and request.body.strip() == item.text.strip():
            raise _Rejected("文字没有变化；如果接受原文请直接批准。")
        return _commit(db, request, batch, ask, item, action, event_id, actor_id, now)
    except _Rejected as error:
        return rejected(str(error))
    except JobAgentError as error:
        return rejected(error.message)


def _commit(
    db: Database, request: HostDecisionRequest, batch: OutreachBatch, ask: OutreachAsk,
    item: OutreachItem, action: str, event_id: str, actor_id: str, now: datetime,
) -> HostReceipt:
    feedback_store = SqliteFeedbackRepository(db)
    state = feedback_store.state(_state_id(ask.ask_id))
    if state is None:
        feedback_store.register(PagedCardState(
            message_id=_state_id(ask.ask_id), batch_id=batch.batch_id, ask_id=ask.ask_id,
            candidate_id=request.candidate_id, expires_at=None,
        ))
        state = feedback_store.state(_state_id(ask.ask_id))
        assert state is not None
    if state.candidate_id != request.candidate_id:
        raise _Rejected("这份清单的决定记录属于其他候选人。")
    key = str(item.number)
    revised = state.model_copy(deep=True)
    revised.revision += 1
    revised.decisions[key] = _DECIDED[action]  # type: ignore[assignment]
    if action == "revise":
        revised.drafts[key] = request.body
    bundle = None
    if action == "approve":
        bundle = _approval(db, batch, item, request, actor_id, now)
        revised.approved_batches[key] = bundle[0].batch_id
    revised.closed = all(str(i.number) in revised.decisions for i in batch.items)
    job = SqliteJobRepository(db).get_job(item.job_id)
    if job is None:
        raise _Rejected("缺少当前完整职位说明，无法保存这次决定。")
    feedback = SourcingFeedback(
        event_id=event_id, idempotency_key=event_id, job_id=item.job_id, source=item.platform,
        query_strategy_version=state.query_strategy_version, action=action,  # type: ignore[arg-type]
        free_text=request.note, content_digest=text_digest(request.body), actor_id=actor_id,
        occurred_at=now, candidate_id=request.candidate_id, original_text=item.text,
        revised_text=request.body if action == "revise" else None,
        jd_text=job.jd_raw, job_title=job.title, company=job.company,
    )
    saved = feedback_store.commit(
        revised, expected_revision=state.revision, event_id=event_id, now=now,
        feedback=feedback, approval_bundle=bundle, withdraw_parent=revised.closed,
    )
    if saved == "duplicate":
        return panel_operation(db.path, request.candidate_id, request.operation_key)
    if saved != "stored":
        raise _Rejected("清单的决定记录刚被更新，请刷新后再操作。")
    return HostReceipt(
        operation_key=request.operation_key, status="saved", event_id=event_id,
        message=_MESSAGES[action],
    )


def _approval(
    db: Database, batch: OutreachBatch, item: OutreachItem, request: HostDecisionRequest,
    actor_id: str, now: datetime,
) -> tuple[OutreachBatch, OutreachAsk, OutreachApproval]:
    """A single-item list from the asked item, approved through the outreach gate."""
    verify_greeting_sources(db, [item], candidate_id=request.candidate_id)
    store, jobs, service = SqliteOutreachRepository(db), SqliteJobRepository(db), OutreachService()
    job = jobs.get_job(item.job_id)
    draft = OutreachDraft(
        job_id=item.job_id, platform=item.platform, text=item.text,
        evidence_ids=item.evidence_ids, variant=item.variant,
        hook_requirement=item.hook_requirement, experiment_id=item.experiment_id,
        written_by=item.written_by, source_binding=item.source_binding,
    )
    tiers = jobs.latest_match_tiers(request.candidate_id, [item.job_id]) or (
        {item.job_id: item.match_tier} if item.match_tier else {}
    )
    child_id = "OBATCH_PANEL_" + canonical_digest(
        [batch.batch_id, item.number, item.item_digest]
    )[7:27].upper()
    report = service.build_batch(
        [draft], jobs={item.job_id: job} if job else {},
        already_contacted=contacted_job_ids(store.list_audits()),
        confirmed_evidence_ids=_owned(db, request.candidate_id), batch_id=child_id,
        created_at=now, policy=batch.policy,
        match_tiers=tiers,
        harness_version=batch.harness_version,
    )
    if (report.batch is None or report.batch.items[0].item_digest != item.item_digest
            or policy_digest(batch.policy) != batch.policy_digest):
        reasons = "、".join(report.rejected[0].reasons) if report.rejected else "内容已变化"
        raise _Rejected("这条招呼不能再批准：" + reasons)
    child = report.batch
    ask = service.ask(child, asked_at=now)
    attestation = (
        f"本人在{CHANNEL}批准第 {item.number} 条最终原文：{item.text}"
        f"（{actor_id}；操作 {request.operation_key}；联系 {request.contact_id}）"
    )
    approval = service.approve(child, ask=ask, numbers=[1], attestation=attestation,
                               approved_at=now)
    return child, ask, approval
