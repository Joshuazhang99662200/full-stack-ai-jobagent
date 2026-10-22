# ruff: noqa: RUF001  -- Chinese chat previews carry full-width punctuation by design.
from pathlib import Path

from tests.cli.test_outreach import invoke


def test_next_is_due_until_a_check_is_recorded(tmp_path: Path) -> None:
    db = ("--database", str(tmp_path / "jobagent.sqlite3"))
    now = ("--now", "2026-10-21T10:00:00+08:00")

    code, first = invoke("patrol", "next", *now, *db)
    assert code == 0 and isinstance(first, dict)
    assert first["active"] and first["due"] and first["mode"] == "base"

    code, recorded = invoke("patrol", "record", *now, *db)
    assert code == 0 and isinstance(recorded, dict) and recorded["mode"] == "base"

    code, second = invoke("patrol", "next", "--now", "2026-10-21T10:30:00+08:00", *db)
    assert code == 0 and isinstance(second, dict) and not second["due"]


def test_a_recruiter_message_tightens_the_rhythm(tmp_path: Path) -> None:
    db = ("--database", str(tmp_path / "jobagent.sqlite3"))
    context = tmp_path / "filter_context.json"
    context.write_text('{"candidate_id": "CAND_001"}', encoding="utf-8")
    invoke("patrol", "record", "--now", "2026-10-21T10:00:00+08:00", *db)
    invoke(
        "conversations", "open", "--platform", "zhaopin", "--company", "某公司",
        "--title", "AI 产品经理", "--filter-context", str(context), *db,
    )

    # The recruiter's message is recorded now, so judge from a moment just after it.
    code, decision = invoke("patrol", "next", *db)

    assert code == 0 and isinstance(decision, dict)
    if decision["active"]:
        assert decision["mode"] == "escalated"


def test_off_hours_are_reported_not_due(tmp_path: Path) -> None:
    code, decision = invoke(
        "patrol", "next", "--now", "2026-10-24T12:00:00+08:00",
        "--database", str(tmp_path / "jobagent.sqlite3"),
    )

    assert code == 0 and isinstance(decision, dict)
    assert decision["mode"] == "off" and not decision["due"]
    assert decision["next_check_at"].startswith("2026-10-25T12:00:00")


def test_a_finished_check_paces_the_next_and_an_unfinished_one_is_resumed(
    tmp_path: Path,
) -> None:
    db = ("--database", str(tmp_path / "jobagent.sqlite3"))
    _, first = invoke("patrol", "record", "--now", "2026-10-21T10:00:00+08:00", *db)
    assert isinstance(first, dict)

    code, finished = invoke(
        "patrol", "finish", first["check_id"], "--now", "2026-10-21T10:20:00+08:00", *db
    )
    assert code == 0 and isinstance(finished, dict)
    _, waiting = invoke("patrol", "next", "--now", "2026-10-21T10:40:00+08:00", *db)
    assert isinstance(waiting, dict) and not waiting["due"]

    _, second = invoke("patrol", "record", "--now", "2026-10-21T11:00:00+08:00", *db)
    assert isinstance(second, dict)
    # The run stopped without finishing; 50 minutes later the next wake resumes it.
    _, resumed = invoke("patrol", "next", "--now", "2026-10-21T11:50:00+08:00", *db)
    assert isinstance(resumed, dict) and resumed["due"]
    assert resumed["abandoned_check_id"] == second["check_id"]


def test_snapshots_are_kept_per_board_and_diffed_against_the_last_one(tmp_path: Path) -> None:
    import json

    db = ("--database", str(tmp_path / "jobagent.sqlite3"))
    first = tmp_path / "first.json"
    first.write_text(json.dumps([
        {"key": "赵先生|腾讯", "recruiter": "赵先生", "company": "腾讯",
         "preview": "您好，我是Alex", "time_label": "23:24", "last_from": "us"},
    ], ensure_ascii=False), encoding="utf-8")
    second = tmp_path / "second.json"
    second.write_text(json.dumps([
        {"key": "赵先生|腾讯", "recruiter": "赵先生", "company": "腾讯",
         "preview": "方便发简历吗", "time_label": "09:10", "unread": 1, "last_from": "them"},
    ], ensure_ascii=False), encoding="utf-8")

    code, one = invoke("patrol", "snapshot", str(first), "--platform", "boss", *db)
    assert code == 0 and isinstance(one, dict) and len(one["diff"]["new"]) == 1
    code, two = invoke("patrol", "snapshot", str(second), "--platform", "boss", *db)
    assert code == 0 and isinstance(two, dict)
    assert [i["key"] for i in two["diff"]["their_new_messages"]] == ["赵先生|腾讯"]

    code, history = invoke("patrol", "snapshots", "--platform", "boss", *db)
    assert code == 0 and isinstance(history, list) and len(history) == 2
    assert history[0]["items"] == 1


def test_a_snapshot_records_read_receipts_for_known_conversations(tmp_path: Path) -> None:
    import json

    db = ("--database", str(tmp_path / "jobagent.sqlite3"))
    invoke(
        "conversations", "adopt", "--platform", "boss", "--company", "腾讯",
        "--title", "AI 产品经理", *db,
    )
    rows = tmp_path / "rows.json"
    rows.write_text(json.dumps([
        {"key": "赵先生|腾讯", "recruiter": "赵先生", "company": "腾讯",
         "preview": "[已读]您好，我是Joshua", "last_from": "us"},
        {"key": "钱女士|阿里", "recruiter": "钱女士", "company": "阿里",
         "preview": "[送达]您好，我是Joshua", "last_from": "us"},
    ], ensure_ascii=False), encoding="utf-8")

    code, result = invoke("patrol", "snapshot", str(rows), "--platform", "boss", *db)

    assert code == 0 and isinstance(result, dict)
    assert result["receipts"]["recorded"] == 1
    assert [
        (row["key"], row["status"], row["reason"]) for row in result["receipts"]["unmatched"]
    ] == [("钱女士|阿里", "delivered", "no_match")]


def test_stored_snapshots_can_be_replayed_into_receipts(tmp_path: Path) -> None:
    import json

    db = ("--database", str(tmp_path / "jobagent.sqlite3"))
    rows = tmp_path / "rows.json"
    rows.write_text(json.dumps([
        {"key": "赵先生|腾讯", "recruiter": "赵先生", "company": "腾讯",
         "preview": "[送达]您好", "last_from": "us"},
    ], ensure_ascii=False), encoding="utf-8")
    later = tmp_path / "later.json"
    later.write_text(json.dumps([
        {"key": "赵先生|腾讯", "recruiter": "赵先生", "company": "腾讯",
         "preview": "[已读]您好", "last_from": "us"},
    ], ensure_ascii=False), encoding="utf-8")
    # The snapshots were kept before the conversation was logged.
    invoke("patrol", "snapshot", str(rows), "--platform", "boss",
           "--now", "2026-10-19T09:00:00+08:00", *db)
    invoke("patrol", "snapshot", str(later), "--platform", "boss",
           "--now", "2026-10-19T15:00:00+08:00", *db)
    invoke(
        "conversations", "adopt", "--platform", "boss", "--company", "腾讯",
        "--title", "AI 产品经理", *db,
    )

    code, replay = invoke("patrol", "receipts", *db)
    assert code == 0 and isinstance(replay, dict)
    assert replay["snapshots"] == 2 and replay["recorded"] == 2
    # Replaying again changes nothing: the first sighting already stands.
    code, again = invoke("patrol", "receipts", *db)
    assert code == 0 and isinstance(again, dict) and again["recorded"] == 0
