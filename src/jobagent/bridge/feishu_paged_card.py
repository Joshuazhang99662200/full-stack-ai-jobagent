# ruff: noqa: RUF001
"""One editable job at a time in a native Feishu 2.0 form."""

from collections.abc import Mapping
from html import escape
from typing import Any

from jobagent.outreach.service import TIER_LABELS
from jobagent.schemas.outreach import OutreachAsk, OutreachBatch
from jobagent.schemas.sourcing_feedback import JobDecisionDetail, PagedCardState

REASONS = {
    "job_dislike": "岗位不喜欢", "salary": "薪资不合适", "location": "地点不合适",
    "direction": "行业／产品方向不喜欢", "level": "职责／级别不合适",
    "copy": "文案不喜欢", "facts": "事实或采集有误", "later": "暂不处理", "other": "其他／不说明",
}


def _markdown(text: str) -> dict[str, Any]:
    return {"tag": "markdown", "content": text}


def _button(label: str, action: str, state: PagedCardState, *, disabled: bool = False,
            style: str = "default") -> dict[str, Any]:
    return {
        "tag": "button", "name": f"{action}_{state.page}_{state.revision}",
        "text": {"tag": "plain_text", "content": label}, "type": style,
        "form_action_type": "submit", "disabled": disabled,
    }


def approval_card(
    batch: OutreachBatch, ask: OutreachAsk, state: PagedCardState,
    details: Mapping[str, JobDecisionDetail], *, notice: str = "",
) -> dict[str, Any]:
    item = batch.items[state.page]
    detail = details.get(item.job_id, JobDecisionDetail())
    match_tier = detail.match_tier or item.match_tier
    tier = TIER_LABELS.get(match_tier, match_tier or "未评估")
    assessment = tier
    if detail.match_score is not None:
        assessment += f" · 已存匹配分 {detail.match_score:.1%}（不是录用概率）"
    if detail.match_version:
        assessment += f"\n评分版本：{escape(detail.match_version)}"
    key = str(item.number)
    decision = state.decisions.get(key)
    decided = decision is not None or state.closed
    description = (
        f"**{escape(item.company)}｜{escape(item.title)}**\n"
        f"薪资：{escape(detail.salary_text or '未提供')} · "
        f"base：{escape(detail.location or '未提供')}\n"
        f"来源：{escape(item.platform)} · [岗位详情]({item.url})"
    )
    judgment = [f"**匹配度**：{assessment}", "**JD 要点**"]
    judgment += [f"· {escape(point)}" for point in detail.points] or [
        "未提取，不用摘要冒充完整 JD。",
    ]
    judgment += ["**适合理由**", *([f"· {escape(x)}" for x in detail.strengths[:3]] or [
        "未提供完整评估；" + escape(item.hook_requirement or "不能据此断言适合。"),
    ])]
    judgment += ["**缺口与待核实**", *([f"· {escape(x)}" for x in detail.gaps[:3]] or [
        "尚无已记录缺口，不等于没有缺口。",
    ])]
    status = {"approved": "本条已批准，等待执行回执。",
              "revision_requested": "JD 已接受；文案待全文重新生成与独立复核，没有发送权。",
              "declined": "本条已回绝，不会领取发送任务。"}
    hint = status.get(decision or "", "接受原稿才批准；修改招呼只记录 JD 意向与文案反馈。")
    if state.demo_mode:
        hint = "合成岗位交互演示；所有决定均无发送权，不进入真实寻源偏好。"
    elif state.candidate_id is None:
        hint = "未绑定候选人；当前卡片仅供审阅、编辑或回绝，不能批准发送。"
    saved_feedback = state.feedback_drafts.get(key, {})
    form: list[dict[str, Any]] = [
        _markdown(f"**招呼语**\n<font color='grey'>{escape(hint)}</font>"),
        {"tag": "input", "name": "greeting", "input_type": "multiline_text", "rows": 4,
         "max_length": 1000, "default_value": state.drafts.get(key, item.text), "width": "fill",
         "disabled": decided},
        {"tag": "select_static", "name": "reason", "width": "fill", "disabled": decided,
         "placeholder": {"tag": "plain_text", "content": "原因或反馈类型（可选）"},
         "options": [{"text": {"tag": "plain_text", "content": label}, "value": value}
                     for value, label in REASONS.items()],
         "initial_option": saved_feedback.get("reason", "other")},
        {"tag": "input", "name": "note", "input_type": "multiline_text", "rows": 2,
         "max_length": 1000, "disabled": decided,
         "default_value": saved_feedback.get("note", ""),
         "placeholder": {"tag": "plain_text",
                         "content": "可选说明；修改招呼表示接受 JD，尚未批准新稿"}},
        {"tag": "column_set", "columns": [
            {"tag": "column", "width": "weighted", "weight": 1, "elements": [
                _button("演示接受原稿" if state.demo_mode else "接受原稿", "approve", state,
                        disabled=decided or (not state.demo_mode and state.candidate_id is None),
                        style="primary_filled")]},
            {"tag": "column", "width": "weighted", "weight": 1, "elements": [
                _button("接受JD，修改招呼", "revise", state,
                        disabled=decided or (not state.demo_mode and state.candidate_id is None))]},
            {"tag": "column", "width": "weighted", "weight": 1, "elements": [
                _button("演示拒绝JD" if state.demo_mode else "JD不适合", "decline", state,
                        disabled=decided, style="danger")]},
        ]},
        {"tag": "column_set", "columns": [
            {"tag": "column", "width": "weighted", "weight": 1, "elements": [
                _button("上一条", "previous", state, disabled=state.page == 0 or state.closed)]},
            {"tag": "column", "width": "weighted", "weight": 1, "elements": [
                _button("下一条", "next", state,
                        disabled=state.page == len(batch.items) - 1 or state.closed)]},
        ]},
    ]
    return {
        "schema": "2.0", "config": {"width_mode": "default", "update_multi": True},
        "header": {"title": {"tag": "plain_text",
                             "content": ("演示 · 无发送权 · " if state.demo_mode else "职位审批 · ")
                             + f"{state.page + 1}/{len(batch.items)}"},
                   "subtitle": {"tag": "plain_text", "content": f"{batch.batch_id} · {ask.ask_id}"},
                   "template": "green" if state.closed else "blue"},
        "body": {"elements": [
            _markdown(description), _markdown("\n".join(judgment)),
            _markdown(escape(notice)) if notice else _markdown(
                "<font color='grey'>上一条／下一条会保存当前编辑，不代表批准或不喜欢。</font>"),
            {"tag": "form", "name": "paged_outreach", "elements": form},
        ]},
    }
