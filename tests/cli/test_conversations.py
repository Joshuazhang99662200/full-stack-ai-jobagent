# ruff: noqa: RUF001  -- Chinese messages carry full-width punctuation by design.
import json
from pathlib import Path

from tests.cli.test_outreach import drafted, invoke
from tests.harness.test_pdf import render, variant


def greeted(tmp_path: Path) -> tuple[tuple[str, str], str, str]:
    """Send item 1 of an approved batch and sync it into a conversation."""
    database, batch_id = drafted(tmp_path)
    db = ("--database", str(database))
    _, ask = invoke("outreach", "ask", batch_id, *db)
    assert isinstance(ask, dict)
    invoke(
        "outreach",
        "approve",
        batch_id,
        "--request",
        ask["ask_id"],
        "--items",
        "1",
        "--answer",
        "发 1",
        *db,
    )
    invoke("outreach", "lease", "boss", "--session", "S1", *db)
    invoke("outreach", "record", batch_id, "1", "--result", "sent", "--session", "S1", *db)

    code, synced = invoke("conversations", "sync-outreach", *db)
    assert code == 0, synced
    assert isinstance(synced, dict) and len(synced["opened"]) == 1
    conversation = synced["opened"][0]
    return db, conversation["conversation_id"], conversation["job_id"]


def test_from_greeting_to_a_sent_resume(tmp_path: Path) -> None:
    db, conversation_id, job_id = greeted(tmp_path)

    code, again = invoke("conversations", "sync-outreach", *db)
    assert isinstance(again, dict) and again["opened"] == []

    code, received = invoke(
        "conversations",
        "inbound",
        conversation_id,
        "--text",
        "您好，方便发份简历吗？",
        "--level",
        "l1",
        "--asks-resume",
        *db,
    )
    assert code == 0, received
    assert isinstance(received, dict) and received["stage"] == "resume_requested"

    _, due = invoke("conversations", "due", *db)
    assert isinstance(due, list) and due[0]["action"] == "tailor_resume"

    variant_path = tmp_path / "variant.json"
    variant_path.write_text(
        variant().model_copy(update={"target_job_id": job_id}).model_dump_json(), "utf-8"
    )
    pdf_path = tmp_path / "resume.pdf"
    render(pdf_path, variant().items[0].text)
    code, attached = invoke(
        "conversations", "attach-resume", conversation_id, str(variant_path), str(pdf_path), *db
    )
    assert code == 0, attached

    code, ask = invoke(
        "conversations",
        "draft-reply",
        conversation_id,
        "--kind",
        "resume",
        "--text",
        "这是我的简历，请查收。",
        *db,
    )
    assert code == 0, ask
    assert isinstance(ask, dict) and "请查收" in ask["question"]
    code, approved = invoke(
        "conversations",
        "approve-reply",
        conversation_id,
        "--request",
        ask["ask_id"],
        "--answer",
        "发",
        *db,
    )
    assert code == 0, approved

    code, gate = invoke("conversations", "reply-gate", conversation_id, "--session", "S1", *db)
    assert isinstance(gate, dict) and gate["allowed"], gate
    assert gate["attachment_digest"].startswith("sha256:")
    other = tmp_path / "other.pdf"
    other.write_bytes(b"%PDF-1.4 another file")
    code, wrong_file = invoke(
        "conversations", "record-reply", conversation_id, "--result", "sent",
        "--session", "S1", "--file", str(other), *db,
    )
    assert code == 1 and isinstance(wrong_file, dict)
    code, recorded = invoke(
        "conversations",
        "record-reply",
        conversation_id,
        "--result",
        "sent",
        "--session",
        "S1",
        "--file",
        str(pdf_path),
        *db,
    )
    assert code == 0, recorded
    assert isinstance(recorded, dict) and recorded["stage"] == "resume_sent"

    _, shown = invoke("conversations", "show", conversation_id, *db)
    assert isinstance(shown, dict) and shown["stage"] == "resume_sent"
    assert [event["kind"] for event in shown["events"]][-2:] == ["reply_result", "stage_changed"]


def test_intent_needs_a_posed_question_and_l3_stays_with_the_person(tmp_path: Path) -> None:
    db, conversation_id, _ = greeted(tmp_path)
    invoke(
        "conversations", "inbound", conversation_id, "--text", "您好，聊聊？", "--level", "l1", *db
    )

    code, refused = invoke(
        "conversations",
        "confirm-intent",
        conversation_id,
        "--request",
        "CASK_NEVER",
        "--answer",
        "有意向",
        *db,
    )
    assert code == 1 and isinstance(refused, dict)

    _, ask = invoke("conversations", "ask-intent", conversation_id, *db)
    assert isinstance(ask, dict)
    code, confirmed = invoke(
        "conversations",
        "confirm-intent",
        conversation_id,
        "--request",
        ask["ask_id"],
        "--answer",
        "有意向",
        *db,
    )
    assert code == 0 and isinstance(confirmed, dict)
    assert confirmed["stage"] == "intent_confirmed"

    invoke(
        "conversations", "inbound", conversation_id, "--text", "加个微信？", "--level", "l3", *db
    )
    code, human_only = invoke(
        "conversations",
        "draft-reply",
        conversation_id,
        "--kind",
        "answer",
        "--text",
        "好的。",
        *db,
    )
    assert code == 1 and isinstance(human_only, dict)
    assert "human_only" in human_only["error"]["details"]["problems"]


def filter_context(tmp_path: Path) -> str:
    path = tmp_path / "filter_context.json"
    path.write_text(
        json.dumps({"candidate_id": "CAND_001", "excluded_role_terms": ["销售", "外包"]}),
        encoding="utf-8",
    )
    return str(path)


def test_a_recruiter_can_open_a_conversation_and_it_can_be_closed(tmp_path: Path) -> None:
    database = tmp_path / "jobagent.sqlite3"
    db = ("--database", str(database))

    code, opened = invoke(
        "conversations",
        "open",
        "--platform",
        "zhaopin",
        "--company",
        "某公司",
        "--title",
        "AI 产品经理",
        "--filter-context",
        filter_context(tmp_path),
        *db,
    )
    assert code == 0 and isinstance(opened, dict) and opened["stage"] == "replied"
    assert opened["screen"] == {"excluded": False, "term": None, "title_unknown": False}
    code, closed = invoke(
        "conversations",
        "transition",
        opened["conversation_id"],
        "--to",
        "closed",
        "--reason",
        "外包驻场，按规则婉拒",
        *db,
    )
    assert code == 0 and isinstance(closed, dict) and closed["stage"] == "closed"
    _, listed = invoke("conversations", "list", *db)
    assert isinstance(listed, list) and json.dumps(listed, ensure_ascii=False).count("closed") == 1


def test_a_recruiter_offering_an_excluded_role_is_screened_out(tmp_path: Path) -> None:
    db = ("--database", str(tmp_path / "jobagent.sqlite3"))

    code, opened = invoke(
        "conversations", "open", "--platform", "zhaopin", "--company", "某人力公司",
        "--title", "AI 产品经理（外包驻场）", "--filter-context", filter_context(tmp_path), *db,
    )

    assert code == 0 and isinstance(opened, dict)
    assert opened["stage"] == "closed"
    assert opened["screen"] == {"excluded": True, "term": "外包", "title_unknown": False}


def test_opening_a_recruiter_conversation_needs_the_filter_context(tmp_path: Path) -> None:
    code, _ = invoke(
        "conversations", "open", "--platform", "zhaopin", "--company", "某公司",
        "--title", "AI 产品经理", "--database", str(tmp_path / "jobagent.sqlite3"),
    )

    assert code != 0


def test_conversations_the_person_started_are_kept_in_their_own_log(tmp_path: Path) -> None:
    db = ("--database", str(tmp_path / "jobagent.sqlite3"))
    invoke(
        "conversations", "open", "--platform", "zhaopin", "--company", "来信公司",
        "--title", "AI 产品经理", "--filter-context", filter_context(tmp_path), *db,
    )
    code, adopted = invoke(
        "conversations", "adopt", "--platform", "boss", "--company", "自找公司",
        "--title", "Agent 产品经理", "--replied", *db,
    )
    assert code == 0 and isinstance(adopted, dict)
    assert adopted["origin"] == "self" and adopted["stage"] == "replied"

    _, mine = invoke("conversations", "list", "--origin", "self", *db)
    assert isinstance(mine, list) and [c["company"] for c in mine] == ["自找公司"]
    _, everything = invoke("conversations", "list", *db)
    assert isinstance(everything, list) and len(everything) == 2


def test_the_same_recruiter_written_differently_is_not_logged_twice(tmp_path: Path) -> None:
    db = ("--database", str(tmp_path / "jobagent.sqlite3"))
    invoke(
        "conversations", "adopt", "--platform", "liepin",
        "--company", "猎头(广州赛睿人力资源有限公司)", "--title", "AI agent产品专家", *db,
    )

    code, again = invoke(
        "conversations", "adopt", "--platform", "liepin",
        "--company", "广州赛睿人力资源有限公司（猎头）", "--title", "AI agent产品专家", *db,
    )
    assert code == 1 and isinstance(again, dict)
    assert again["error"]["details"]["existing"]

    code, inbound_dup = invoke(
        "conversations", "open", "--platform", "liepin", "--company", "广州赛睿人力资源有限公司",
        "--title", "AI agent产品专家", "--filter-context", filter_context(tmp_path), *db,
    )
    assert code == 1 and isinstance(inbound_dup, dict)


def test_screening_reads_the_company_and_flags_an_unknown_title(tmp_path: Path) -> None:
    db = ("--database", str(tmp_path / "jobagent.sqlite3"))

    code, advisory = invoke(
        "conversations", "open", "--platform", "boss", "--company", "上海某外包服务(徐女士)",
        "--title", "未注明", "--filter-context", filter_context(tmp_path), *db,
    )
    assert code == 0 and isinstance(advisory, dict)
    assert advisory["screen"]["excluded"] and advisory["stage"] == "closed"

    code, unknown = invoke(
        "conversations", "open", "--platform", "boss", "--company", "某科技(李女士)",
        "--title", "未注明", "--filter-context", filter_context(tmp_path), *db,
    )
    assert code == 0 and isinstance(unknown, dict)
    assert unknown["screen"] == {"excluded": False, "term": None, "title_unknown": True}


def test_a_reply_redrafted_before_approval_is_marked_as_edited(tmp_path: Path) -> None:
    db, conversation_id, _ = greeted(tmp_path)
    invoke(
        "conversations", "inbound", conversation_id, "--text", "您好？", "--level", "l1", *db
    )
    _, first = invoke(
        "conversations", "draft-reply", conversation_id, "--kind", "answer",
        "--text", "您好，在的。", *db,
    )
    code, second = invoke(
        "conversations", "draft-reply", conversation_id, "--kind", "answer",
        "--text", "您好，在的，方便聊聊。", *db,
    )
    assert code == 0 and isinstance(first, dict) and isinstance(second, dict), second
    assert second["original_reply_digest"] == first["reply_digest"]
    assert second["harness_version"].startswith("HVER_")

    invoke(
        "conversations", "approve-reply", conversation_id, "--request", second["ask_id"],
        "--answer", "发", *db,
    )
    _, shown = invoke("conversations", "show", conversation_id, *db)
    assert isinstance(shown, dict)
    approved = shown["events"][-1]
    assert approved["kind"] == "reply_approved" and approved["edited_by_human"] is True
