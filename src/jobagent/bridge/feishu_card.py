# ruff: noqa: RUF001  -- Cards for the person are written in Chinese.
"""Feishu cards that put an outreach question to the person and show what came of it.

The approval card mirrors the panel in the chat window: one block per greeting
with a box to tick and the words in an editable field, and one submit button.
Nothing here decides anything; it only builds card JSON and reads a submission.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from jobagent.outreach.service import TIER_LABELS
from jobagent.schemas.outreach import OutreachAsk, OutreachBatch

FORM = "outreach_approval"


@dataclass(frozen=True)
class Submission:
    chosen: list[int]
    # Ticked items whose words the person changed, by number.
    edited: dict[int, str]


@dataclass(frozen=True)
class JobDetail:
    """What the person needs beside a greeting to judge it: where, and what the JD asks."""

    location: str | None = None
    keywords: list[str] = field(default_factory=list)
    # The JD's own words for its main requirements, most binding first.
    points: list[str] = field(default_factory=list)


def _markdown(content: str) -> dict[str, Any]:
    return {"tag": "markdown", "content": content}


def _describe(head: str, detail: JobDetail | None, hook: str | None) -> str:
    lines = [head]
    if detail is not None and detail.keywords:
        lines.append(f"**JD 关键词**：{' · '.join(detail.keywords)}")
    if detail is not None:
        lines += [f"<font color='grey'>· 「{point}」</font>" for point in detail.points]
    if hook:
        lines.append(f"<font color='grey'>这条招呼对上：{hook}</font>")
    return "\n".join(lines)


def approval_card(
    batch: OutreachBatch, ask: OutreachAsk, details: Mapping[str, JobDetail] | None = None
) -> dict[str, Any]:
    rewritten = any(item.written_by == "person" for item in batch.items)
    hint = (
        "这是你改写后的原文，确认无误再勾选提交。"
        if rewritten
        else "勾选要发的条目，可直接改原文。点提交即批准勾选的条目，改过的按改后原文发送。"
    )
    elements: list[dict[str, Any]] = []
    for item in batch.items:
        tier = TIER_LABELS.get(item.match_tier, item.match_tier or "未评估")
        mark = "（本人改写）" if item.written_by == "person" else ""
        detail = (details or {}).get(item.job_id)
        where = f" · {detail.location}" if detail is not None and detail.location else ""
        head = (
            f"**{item.number}. {item.company}｜{item.title}**{mark}\n"
            f"<font color='grey'>{item.platform} · {tier}{where}</font>"
        )
        elements += [
            _markdown(_describe(head, detail, item.hook_requirement)),
            {
                "tag": "checker",
                "name": f"pick_{item.number}",
                "checked": False,
                "text": {"tag": "plain_text", "content": f"发送第 {item.number} 条"},
            },
            {
                "tag": "input",
                "name": f"text_{item.number}",
                "input_type": "multiline_text",
                "rows": 4,
                "max_length": 1000,
                "default_value": item.text,
                "width": "fill",
            },
        ]
    elements.append(
        {
            "tag": "button",
            "name": "submit",
            "text": {"tag": "plain_text", "content": "提交审批"},
            "type": "primary_filled",
            "width": "fill",
            "form_action_type": "submit",
            "confirm": {
                "title": {"tag": "plain_text", "content": "提交审批"},
                "text": {
                    "tag": "plain_text",
                    "content": "勾选的条目将被批准发送，提交后这张卡不能再改。",
                },
            },
        }
    )
    return {
        "schema": "2.0",
        "config": {"width_mode": "default"},
        "header": {
            "title": {"tag": "plain_text", "content": f"首条招呼审批 · {len(batch.items)} 条"},
            "subtitle": {"tag": "plain_text", "content": f"{batch.batch_id} · {ask.ask_id}"},
            "template": "blue",
        },
        "body": {
            "elements": [
                _markdown(f"<font color='grey'>{hint}</font>"),
                {"tag": "form", "name": FORM, "elements": elements},
            ]
        },
    }


def result_card(title: str, lines: list[str], *, ok: bool) -> dict[str, Any]:
    return {
        "schema": "2.0",
        "config": {"width_mode": "default"},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": "green" if ok else "red",
        },
        "body": {"elements": [_markdown("\n".join(lines) or " ")]},
    }


def _ticked(value: object) -> bool:
    return value is True or str(value).strip().lower() == "true"


def read_submission(form_value: dict[str, Any], batch: OutreachBatch) -> Submission:
    chosen: list[int] = []
    edited: dict[int, str] = {}
    for item in batch.items:
        if not _ticked(form_value.get(f"pick_{item.number}")):
            continue
        chosen.append(item.number)
        text = form_value.get(f"text_{item.number}")
        if isinstance(text, str) and text.strip() and text.strip() != item.text.strip():
            edited[item.number] = text.strip()
    return Submission(chosen, edited)
