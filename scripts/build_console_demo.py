# ruff: noqa: RUF001 -- Preserve Chinese fixture copy exactly.
"""Generate synthetic console material from the authoritative Python contracts."""

import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from jobagent.console.activities import validate_activities
from jobagent.console.projection import definitions
from jobagent.jobs.jd_snapshot import text_digest
from jobagent.schemas.console import (
    ConsoleActivity,
    ConsoleFilterContext,
    ConsoleJob,
    ConsoleMatchContext,
    ConsoleRun,
    ConsoleSnapshot,
    ConsoleSource,
)
from jobagent.schemas.harness import HarnessRun, RunPhase
from jobagent.schemas.jobs import FilterDecision, HardFilterResult, MatchDecision, MatchResult
from jobagent.schemas.pipeline import PipelineHistory, PipelineJob, PipelineMeta, PipelineState

ANCHOR = datetime.fromisoformat("2026-10-31T10:00:00+08:00")
CANDIDATE = "CAND_DEMO"
JD = "这是完整的合成 JD 正文。最后一行也必须保留。"
DRAFT = "您好，这是供审核的合成招呼语，尚未发送。"
HISTORICAL_GREETING = "您好，这是已核验回读的合成历史招呼语。"


def clock(minute: int) -> datetime:
    return datetime.fromisoformat(f"2026-10-31T09:{minute:02d}:00+08:00")


def activity(
    run_id: str,
    stage: Literal[
        "fetch", "detail", "match", "draft_greeting", "review", "approval", "readback", "report"
    ],
    status: Literal["started", "heartbeat", "waiting", "completed", "failed"],
    minute: int,
    message: str,
    job_id: str | None = None,
) -> ConsoleActivity:
    return ConsoleActivity(
        event_id=f"DEMO_{run_id}_{stage}_{status}_{minute}",
        run_id=run_id,
        candidate_id=CANDIDATE,
        activity_id=f"ACT_{stage}",
        activity=stage,
        status=status,
        occurred_at=clock(minute),
        recorded_at=clock(minute),
        owner="合成宿主",
        job_id=job_id,
        checkpoint_reference="DEMO_CHECKPOINT",
        message=message,
    )


def run(letter: str, phase: RunPhase, minute: int, updated: datetime = ANCHOR) -> HarnessRun:
    return HarnessRun(
        run_id=f"RUN_{letter * 32}",
        candidate_id=CANDIDATE,
        runtime_digest=text_digest("SYNTHETIC_CONSOLE_RUNTIME"),
        host="codex",
        phase=phase,
        session_id="DEMO_SESSION",
        created_at=clock(minute),
        updated_at=updated,
    )


def job(
    title: str,
    letter: str,
    *,
    interview: bool = False,
    abandoned: bool = False,
    paused: bool = False,
    score: float | None = None,
    decision: MatchDecision = MatchDecision.STRONG_MATCH,
    feasibility: FilterDecision = FilterDecision.PASS,
) -> ConsoleJob:
    pipeline_id = f"PIPE_{letter * 16}"
    path: list[PipelineState] = ["draft_pending"]
    interview = interview or abandoned
    if interview:
        path.extend(["greeting_sent", "greeting_read", "initial_contact", "interview_pending"])
    if abandoned:
        path.append("abandoned")
    minutes = [0, 5, 6, 8, 30, 45]
    history = []
    for index, state in enumerate(path):
        kind: Literal["owner_message", "send_audit", "list_status", "conversation_message"]
        if state == "greeting_sent":
            kind = "send_audit"
        elif state == "greeting_read":
            kind = "list_status"
        elif state in {"initial_contact", "interview_pending"}:
            kind = "conversation_message"
        else:
            kind = "owner_message"
        history.append(
            PipelineHistory(
                history_id=f"DEMO_HISTORY_{letter}_{index}",
                pipeline_id=pipeline_id,
                from_state=path[index - 1] if index else None,
                to_state=state,
                changed_at=clock(minutes[index]),
                evidence_kind=kind,
                evidence_reference=f"DEMO_EVIDENCE_{letter}_{index}",
                reason_code="user_abandoned" if state == "abandoned" else "normal",
            )
        )
    record = PipelineJob(
        pipeline_id=pipeline_id,
        candidate_id=CANDIDATE,
        job_id=f"DEMO_{letter}",
        platform="boss" if letter != "C" else "zhaopin",
        job_url=f"https://example.com/synthetic-job-{letter.lower()}",
        title=title,
        company="合成机构",
        location="示例地区",
        salary_raw="未提供",
        salary_verified="review",
        jd_text=JD,
        jd_text_hash=text_digest(JD),
        draft_greeting=DRAFT,
        draft_version="DEMO_DRAFT_V1",
        draft_digest=text_digest(DRAFT),
        sent_greeting=HISTORICAL_GREETING if interview else None,
        sent_text_hash=text_digest(HISTORICAL_GREETING) if interview else None,
        sent_at=clock(5) if interview else None,
        send_readback="exact" if interview else None,
        pipeline_state=path[-1],
        state_reason="user_abandoned" if abandoned else None,
        state_changed_at=history[-1].changed_at,
        entered_at=history[0].changed_at,
        updated_at=ANCHOR,
    )
    meta = PipelineMeta(
        pipeline_id=pipeline_id,
        version=len(history),
        proof_status="verified" if interview else "not_sent",
        entered_evidence_reference=f"DEMO_EVIDENCE_{letter}_0",
        last_evidence_reference=history[-1].evidence_reference,
        read_at=clock(6) if interview else None,
        last_substantive_at=clock(30) if interview else None,
        sent_greeting_version="DEMO_HISTORICAL_V1" if interview else None,
        abandoned_at=clock(45) if abandoned else None,
        paused=paused,
        pause_reason="合成暂停，等待核对" if paused else None,
    )
    item = ConsoleJob(job=record, meta=meta, history=history)
    if score is not None:
        item.match_result = MatchResult(
            overall=score,
            decision=decision,
            strengths=["合成证据与岗位要求相符，仅用于展示存量评估。"],
        )
        item.match_context = ConsoleMatchContext(
            job_id=record.job_id,
            updated_at=clock(40),
            policy_digest=text_digest("SYNTHETIC_POLICY"),
            evidence_digest=text_digest("SYNTHETIC_EVIDENCE"),
            requirements_digest=text_digest("SYNTHETIC_REQUIREMENTS"),
        )
        item.hard_filter_result = HardFilterResult(decision=feasibility)
        item.hard_filter_context = ConsoleFilterContext(
            job_id=record.job_id,
            updated_at=clock(40),
            policy_digest=text_digest("SYNTHETIC_FILTER_POLICY"),
        )
    return item


def build_demo() -> ConsoleSnapshot:
    current = run("A", RunPhase.RUNNING, 50)
    waiting = run("B", RunPhase.WAITING_FOR_APPROVAL, 20)
    ended = run("C", RunPhase.COMPLETED, 10, clock(18))
    stale = run("D", RunPhase.RUNNING, 10, clock(10))
    runs = [
        ConsoleRun(
            run=current,
            freshness="current",
            activities=[
                activity(current.run_id, "fetch", "started", 50, "开始采集。"),
                activity(current.run_id, "fetch", "completed", 54, "采集完成。"),
                activity(current.run_id, "detail", "started", 54, "开始读取详情。"),
                activity(
                    current.run_id, "detail", "heartbeat", 59, "正在读取岗位详情，恢复点已保存。"
                ),
            ],
        ),
        ConsoleRun(
            run=waiting,
            freshness="current",
            activities=[
                activity(waiting.run_id, "fetch", "started", 20, "开始采集。"),
                activity(waiting.run_id, "fetch", "completed", 25, "采集完成。"),
                activity(waiting.run_id, "match", "started", 25, "核对证据。"),
                activity(waiting.run_id, "match", "completed", 28, "匹配完成。"),
                activity(waiting.run_id, "draft_greeting", "started", 28, "开始起草。"),
                activity(waiting.run_id, "draft_greeting", "completed", 32, "草稿已保存。"),
                activity(waiting.run_id, "review", "started", 32, "开始复核。"),
                activity(waiting.run_id, "review", "completed", 35, "复核完成。"),
                activity(waiting.run_id, "approval", "started", 35, "准备审批。"),
                activity(waiting.run_id, "approval", "waiting", 59, "等待本人逐项审批。"),
            ],
        ),
        ConsoleRun(run=ended, freshness="terminal", activities=[]),
        ConsoleRun(
            run=stale,
            freshness="stale",
            activities=[
                activity(stale.run_id, "fetch", "started", 10, "心跳已过期，请核验恢复点。"),
            ],
        ),
    ]
    for item in runs:
        job_id = "DEMO_A" if item.run.run_id == current.run_id else "DEMO_B"
        if item.run.run_id == stale.run_id:
            job_id = "DEMO_E"
        item.activities = [entry.model_copy(update={"job_id": job_id}) for entry in item.activities]
    # A different job and an already active job overlap the current read on the same clock.
    runs[1].activities.extend(
        [
            activity(waiting.run_id, "detail", "started", 55, "并行核对同一岗位详情。", "DEMO_A"),
            activity(waiting.run_id, "detail", "heartbeat", 59, "详情复核仍在执行。", "DEMO_A"),
        ]
    )
    runs[0].activities.extend(
        [
            activity(
                current.run_id, "report", "started", 56, "生成轮次级进度汇总，未归属单个岗位。"
            ),
            activity(current.run_id, "report", "heartbeat", 59, "轮次级汇总仍在执行。"),
        ]
    )
    for item in runs:
        validate_activities(item.activities, item.run, ANCHOR)
    result = ConsoleSnapshot(
        candidate_id=CANDIDATE,
        generated_at=ANCHOR,
        sources=[
            ConsoleSource(name="pipeline", status="complete", message="合成岗位及历史。"),
            ConsoleSource(name="harness", status="complete", message="合成运行记录。"),
            ConsoleSource(
                name="assessments", status="complete", message="合成存量评估，未重新求值。"
            ),
            ConsoleSource(name="activities", status="complete", message="合成宿主观察。"),
            ConsoleSource(
                name="approvals",
                status="unsupported",
                message="尚未关联候选人的审批材料；运行等待状态单独展示。",
            ),
        ],
        jobs=[
            job("数据工程师", "A", score=0.91),
            job(
                "交互设计师", "B", interview=True, score=0.72, decision=MatchDecision.POSSIBLE_MATCH
            ),
            job("研究分析师", "C"),
            job("运营策略", "D", abandoned=True, score=0.99),
            job("质量工程师", "E", paused=True, score=0.96, feasibility=FilterDecision.REVIEW),
        ],
        runs=runs,
    )
    return ConsoleSnapshot.model_validate_json(result.model_dump_json())


if __name__ == "__main__":
    destination = Path(__file__).resolve().parents[1] / "frontend/src/demo.json"
    destination.write_text(build_demo().model_dump_json(indent=2) + "\n", encoding="utf-8")
    destination.with_name("demo-definitions.json").write_text(
        json.dumps(definitions(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Validated synthetic fixture: {destination}")
