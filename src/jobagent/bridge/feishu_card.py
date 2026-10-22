# ruff: noqa: RUF001  -- Cards for the person are written in Chinese.
"""Feishu cards that put an outreach question to the person and show what came of it.

The approval card mirrors the panel in the chat window: one block per greeting
with a box to tick and the words in an editable field, and one submit button.
Nothing here decides anything; it only builds card JSON and reads a submission.
"""

from dataclasses import dataclass
from typing import Any

from jobagent.outreach.service import TIER_LABELS
from jobagent.schemas.outreach import OutreachAsk, OutreachBatch

FORM = "outreach_approval"


@dataclass(frozen=True)
class Submission:
    chosen: list[int]
    # Ticked items whose words the person changed, by number.
    edited: dict[int, str]


def _markdown(content: str) -> dict[str, Any]:
    return {"tag": "markdown", "content": content}


def approval_card(batch: OutreachBatch, ask: OutreachAsk) -> dict[str, Any]:
    rewritten = any(item.written_by == "person" for item in batch.items)
    hint = (
        "这是你改写后的原文，确认无误再勾选提交。"
        if rewritten
        else "勾选要发的条目，可直接改原文。改过的条目会再发一张确认卡，确认后才登记。"
    )
    elements: list[dict[str, Any]] = []
    for item in batch.items:
        tier = TIER_LABELS.get(item.match_tier, item.match_tier or "未评估")
        mark = "（本人改写）" if item.written_by == "person" else ""
        elements += [
            _markdown(
                f"**{item.number}. {item.company}｜{item.title}**{mark}\n"
                f"<font color='grey'>{item.platform} · {tier}</font>"
            ),
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
                    "content": "只登记勾选的条目，提交后这张卡不能再改。",
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
