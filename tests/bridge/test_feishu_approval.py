# ruff: noqa: RUF001  -- Cards for the person are written in Chinese.
import json
from pathlib import Path
from typing import Any

from jobagent.bridge import feishu_approval, feishu_card, status
from jobagent.storage.database import Database
from jobagent.storage.outreach_repository import SqliteOutreachRepository
from tests.cli.test_outreach import drafted, invoke

OWNER = "ou_owner"


def _asked(tmp_path: Path) -> tuple[Path, str, str]:
    database, batch_id = drafted(tmp_path)
    _, ask = invoke("outreach", "ask", batch_id, "--database", str(database))
    assert isinstance(ask, dict)
    return database, batch_id, ask["ask_id"]


def _store(database: Path) -> SqliteOutreachRepository:
    return SqliteOutreachRepository(Database(database))


def _carded(tmp_path: Path) -> tuple[Path, str, str]:
    database, batch_id, ask_id = _asked(tmp_path)
    feishu_approval.register_card(database, "om_card", ask_id=ask_id, batch_id=batch_id)
    return database, batch_id, ask_id


def _event(form: dict[str, Any], *, event_id: str = "ev_1", operator: str = OWNER,
           message_id: str = "om_card") -> dict[str, Any]:
    return {
        "type": "card.action.trigger", "event_id": event_id, "operator_id": operator,
        "message_id": message_id, "action_tag": "button", "token": "tok",
        "form_value": json.dumps(form, ensure_ascii=False),
    }


def _batches(database: Path) -> list[str]:
    with Database(database).connect() as connection:
        return [r[0] for r in connection.execute("SELECT batch_id FROM outreach_batches")]


def _texts(database: Path, batch_id: str) -> dict[int, str]:
    batch = _store(database).get_batch(batch_id)
    assert batch is not None
    return {item.number: item.text for item in batch.items}


def test_card_mirrors_the_panel_one_tick_box_and_editable_text_per_item(tmp_path: Path) -> None:
    database, batch_id, ask_id = _asked(tmp_path)
    store = _store(database)
    batch, ask = store.get_batch(batch_id), store.get_ask(ask_id)
    assert batch is not None and ask is not None

    card = feishu_card.approval_card(batch, ask)

    form = card["body"]["elements"][1]
    assert card["schema"] == "2.0" and form["tag"] == "form"
    names = [e.get("name") for e in form["elements"]]
    assert names[-1] == "submit" and form["elements"][-1]["form_action_type"] == "submit"
    for item in batch.items:
        assert f"pick_{item.number}" in names
        field = next(e for e in form["elements"] if e.get("name") == f"text_{item.number}")
        assert field["default_value"] == item.text


def test_reading_a_submission_keeps_only_ticked_items_and_their_edits(tmp_path: Path) -> None:
    database, batch_id, _ = _asked(tmp_path)
    batch = _store(database).get_batch(batch_id)
    assert batch is not None
    original = batch.items[0].text

    picked = feishu_card.read_submission(
        {"pick_1": True, "text_1": original, "pick_2": "false", "text_2": "改了但没勾"}, batch
    )
    edited = feishu_card.read_submission({"pick_1": "true", "text_1": "新的原文"}, batch)

    assert picked.chosen == [1] and picked.edited == {}
    assert edited.chosen == [1] and edited.edited == {1: "新的原文"}


def test_ticked_unedited_items_are_registered_with_the_submission_as_answer(
    tmp_path: Path,
) -> None:
    database, batch_id, ask_id = _carded(tmp_path)
    texts = _texts(database, batch_id)

    outcome = feishu_approval.handle_card_event(
        database, _event({"pick_2": True, "text_2": texts[2], "pick_1": False}), owner=OWNER
    )

    approval = _store(database).get_approval(batch_id)
    assert outcome.status == "registered" and approval is not None
    assert approval.approved_numbers == [2] and approval.ask_id == ask_id
    assert "飞书卡片" in approval.attestation and OWNER in approval.attestation
    assert status.pending_approvals(database) == []


def test_a_card_is_answered_once(tmp_path: Path) -> None:
    database, batch_id, _ = _carded(tmp_path)
    texts = _texts(database, batch_id)
    form = {"pick_1": True, "text_1": texts[1]}
    feishu_approval.handle_card_event(database, _event(form), owner=OWNER)

    again = feishu_approval.handle_card_event(database, _event(form), owner=OWNER)
    later = feishu_approval.handle_card_event(
        database, _event(form, event_id="ev_2"), owner=OWNER
    )

    assert again.status == "duplicate"
    assert later.status == "rejected" and "已处理" in later.lines[0]


def test_someone_else_or_an_unknown_card_registers_nothing(tmp_path: Path) -> None:
    database, batch_id, _ = _carded(tmp_path)
    form = {"pick_1": True, "text_1": _texts(database, batch_id)[1]}

    stranger = feishu_approval.handle_card_event(
        database, _event(form, operator="ou_stranger"), owner=OWNER
    )
    unknown = feishu_approval.handle_card_event(
        database, _event(form, event_id="ev_3", message_id="om_other"), owner=OWNER
    )

    assert stranger.status == unknown.status == "rejected"
    assert _store(database).get_approval(batch_id) is None


def test_nothing_ticked_leaves_the_card_open(tmp_path: Path) -> None:
    database, batch_id, _ = _carded(tmp_path)
    texts = _texts(database, batch_id)

    empty = feishu_approval.handle_card_event(database, _event({"pick_1": False}), owner=OWNER)
    then = feishu_approval.handle_card_event(
        database, _event({"pick_1": True, "text_1": texts[1]}, event_id="ev_2"), owner=OWNER
    )

    assert empty.status == "rejected" and then.status == "registered"


def test_a_ticked_rewrite_is_approved_as_rewritten_in_one_click(tmp_path: Path) -> None:
    database, batch_id, _ = _carded(tmp_path)
    texts = _texts(database, batch_id)
    rewritten = texts[1] + "我自己补一句，不受字数限制。"

    outcome = feishu_approval.handle_card_event(
        database,
        _event({"pick_1": True, "text_1": rewritten, "pick_2": True, "text_2": texts[2]}),
        owner=OWNER,
    )

    store = _store(database)
    original = store.get_approval(batch_id)
    assert outcome.status == "registered" and original is not None
    assert original.approved_numbers == [2]
    rewrites = [b for b in _batches(database) if b != batch_id]
    assert len(rewrites) == 1
    batch = store.get_batch(rewrites[0])
    approval = store.get_approval(rewrites[0])
    assert batch is not None and approval is not None
    assert [i.text for i in batch.items] == [rewritten]
    assert batch.items[0].written_by == "person"
    assert approval.approved_numbers == [1] and rewritten in approval.attestation
    assert status.pending_approvals(database) == []


def test_a_rewrite_that_breaks_the_rules_is_not_approved(tmp_path: Path) -> None:
    database, batch_id, _ = _carded(tmp_path)

    outcome = feishu_approval.handle_card_event(
        database, _event({"pick_1": True, "text_1": "做过 5 年投研。方便聊聊吗？"}), owner=OWNER
    )

    assert outcome.status == "rejected" and "contains_number" in outcome.lines[0]
    assert _batches(database) == [batch_id]
    texts = _texts(database, batch_id)
    fixed = feishu_approval.handle_card_event(
        database, _event({"pick_1": True, "text_1": texts[1]}, event_id="ev_2"), owner=OWNER
    )
    assert fixed.status == "registered"


def test_listener_updates_the_card_in_place(tmp_path: Path) -> None:
    database, batch_id, _ = _carded(tmp_path)
    texts = _texts(database, batch_id)
    updates: list[tuple[str, dict[str, Any]]] = []

    lines = [
        "not json",
        json.dumps({"type": "card.action.trigger", "action_tag": "checker", "event_id": "x"}),
        json.dumps(_event({"pick_1": True, "text_1": texts[1] + "改"})),
    ]
    outcomes = feishu_approval.listen(
        lines, database, owner=OWNER, update=lambda token, card: updates.append((token, card))
    )

    assert [o.status for o in outcomes] == ["registered"]
    assert updates[0][0] == "tok" and updates[0][1]["header"]["template"] == "green"


def test_listening_needs_an_app_bot_and_an_owner(tmp_path: Path) -> None:
    database, _, _ = _asked(tmp_path)
    (database.parent / "feishu_push.json").write_text(
        json.dumps({"webhook": "https://open.feishu.cn/x"}), encoding="utf-8"
    )

    code, report = invoke("notify", "feishu-listen", "--database", str(database))

    assert code == 1 and isinstance(report, dict) and "owner" in report["error"]["message"]


def test_the_card_shows_jd_keywords_and_original_requirements(tmp_path: Path) -> None:
    from jobagent.schemas.jobs import JobRequirement, JobRequirementProfile
    from jobagent.storage.job_repository import SqliteJobRepository

    database, batch_id, ask_id = _asked(tmp_path)
    store = _store(database)
    batch, ask = store.get_batch(batch_id), store.get_ask(ask_id)
    assert batch is not None and ask is not None
    job_id = batch.items[0].job_id

    def req(n: int, priority: str, span: str, keywords: list[str]) -> JobRequirement:
        return JobRequirement(id=f"REQ_{n}", statement=span, category="skill",
                              priority=priority, source_span=span, keywords=keywords)

    SqliteJobRepository(Database(database)).save_requirements(JobRequirementProfile(
        job_id=job_id,
        requirements=[
            req(1, "context", "了解 MCP 等基础概念", ["MCP"]),
            req(2, "must", "本科及以上学历", ["本科"]),
            req(3, "must", "1-3 年 B 端 / SaaS 产品经验", ["B端", "SaaS"]),
            req(4, "preferred", "有 Agent 工作流设计经验", ["Agent"]),
        ],
    ))

    details = feishu_approval.card_details(database, batch)
    card = feishu_card.approval_card(batch, ask, details)

    text = json.dumps(card, ensure_ascii=False)
    assert "Agent · MCP · B端 · SaaS" in text
    assert "1-3 年 B 端 / SaaS 产品经验" in text and "本科及以上学历" not in text
    assert text.index("1-3 年 B 端") < text.index("有 Agent 工作流") < text.index("了解 MCP")
    other = batch.items[1].job_id
    assert details.get(other) is None or details[other].points == []
