# ruff: noqa: RUF001  -- Messages to the person are written in Chinese.
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jobagent.bridge import feishu_push
from tests.cli.test_outreach import drafted, invoke

NOW = datetime(2026, 10, 22, 4, 0, tzinfo=UTC)


class Recorder:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[tuple[str, str]] = []
        self.fail = fail

    def __call__(self, markdown: str, key: str) -> None:
        if self.fail:
            raise feishu_push.PushError("lark-cli exited 1")
        self.sent.append((markdown, key))


def _asked(tmp_path: Path) -> tuple[Path, str, str]:
    database, batch_id = drafted(tmp_path)
    _, ask = invoke("outreach", "ask", batch_id, "--database", str(database))
    assert isinstance(ask, dict)
    return database, batch_id, ask["ask_id"]


def _inbound(database: Path, text: str) -> None:
    con = sqlite3.connect(database)
    con.execute(
        "INSERT INTO conversations VALUES (?, ?, ?, ?, ?)",
        ("CONV_X", "boss", None, json.dumps({"company": "字节跳动", "title": "AI产品经理"}),
         "2026-10-22T03:00:00+00:00"),
    )
    con.execute(
        "INSERT INTO conversation_events VALUES (?, ?, ?, ?, ?, ?)",
        ("CEVT_X_2", "CONV_X", 2, "inbound",
         json.dumps({"inbound": {"text": text, "level": "l3"}}), "2026-10-22T03:30:00+00:00"),
    )
    con.commit()
    con.close()


def _matched(database: Path, decision: str) -> str:
    con = sqlite3.connect(database)
    job_id = con.execute("SELECT job_id FROM normalized_jobs LIMIT 1").fetchone()[0]
    con.execute("PRAGMA foreign_keys = OFF")
    con.execute(
        "INSERT INTO job_matches VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("CAND_001", job_id, "e", "r", "p", json.dumps({"decision": decision}),
         "2026-10-22T03:00:00+00:00"),
    )
    con.commit()
    con.close()
    return job_id


def test_new_question_is_pushed_once_with_its_full_text(tmp_path: Path) -> None:
    database, batch_id, ask_id = _asked(tmp_path)
    send = Recorder()

    first = feishu_push.push(database, send=send, now=NOW)
    again = feishu_push.push(database, send=send, now=NOW)

    assert first["sent"] is True and again["sent"] is False
    assert len(send.sent) == 1
    markdown, key = send.sent[0]
    assert batch_id in markdown and "方便聊聊吗" in markdown
    assert f"审批 {batch_id}：发" in markdown
    assert key.startswith("jobagent-") and len(key) <= 50
    assert f"ask:{ask_id}" in first["keys"]


def test_recruiter_reply_and_promising_job_are_updates(tmp_path: Path) -> None:
    database, _, _ = _asked(tmp_path)
    feishu_push.push(database, send=Recorder(), now=NOW)
    _inbound(database, "看一下简历")
    job_id = _matched(database, "strong_match")
    send = Recorder()

    report = feishu_push.push(database, send=send, now=NOW)

    assert report["sent"] is True
    markdown = send.sent[0][0]
    assert "字节跳动" in markdown and "看一下简历" in markdown
    assert f"job:{job_id}" in report["keys"]


def test_weak_matches_do_not_trigger_a_push(tmp_path: Path) -> None:
    database, _, _ = _asked(tmp_path)
    feishu_push.push(database, send=Recorder(), now=NOW)
    _matched(database, "weak_match")
    send = Recorder()

    assert feishu_push.push(database, send=send, now=NOW)["sent"] is False
    assert send.sent == []


def test_a_finished_patrol_alone_is_not_an_update(tmp_path: Path) -> None:
    database, _, _ = _asked(tmp_path)
    feishu_push.push(database, send=Recorder(), now=NOW)
    db = ("--database", str(database))
    _, check = invoke("patrol", "record", *db, "--now", "2026-10-22T03:00:00+00:00")
    assert isinstance(check, dict)
    invoke("patrol", "finish", check["check_id"], *db, "--now", "2026-10-22T03:20:00+00:00")
    send = Recorder()

    quiet = feishu_push.push(database, send=send, now=NOW)
    _inbound(database, "方便电话吗")
    loud = feishu_push.push(database, send=send, now=NOW)

    assert quiet["sent"] is False and loud["sent"] is True
    assert len(send.sent) == 1 and "巡检" in send.sent[0][0]


def test_failed_send_keeps_the_updates_for_the_next_try(tmp_path: Path) -> None:
    database, _, _ = _asked(tmp_path)

    with pytest.raises(feishu_push.PushError):
        feishu_push.push(database, send=Recorder(fail=True), now=NOW)
    send = Recorder()
    report = feishu_push.push(database, send=send, now=NOW)

    assert report["sent"] is True and len(send.sent) == 1


def test_dry_run_sends_nothing_and_remembers_nothing(tmp_path: Path) -> None:
    database, _, _ = _asked(tmp_path)
    send = Recorder()

    preview = feishu_push.push(database, send=send, now=NOW, dry_run=True)

    assert preview["sent"] is False and "方便聊聊吗" in preview["markdown"]
    assert send.sent == []
    assert feishu_push.push(database, send=send, now=NOW)["sent"] is True


def test_auto_push_does_nothing_without_a_configured_recipient(tmp_path: Path) -> None:
    database, _, _ = _asked(tmp_path)

    assert feishu_push.auto_push(database) is None


def test_auto_push_reports_a_failure_instead_of_raising(tmp_path: Path) -> None:
    database, _, _ = _asked(tmp_path)
    (database.parent / feishu_push.CONFIG).write_text(
        json.dumps({"chat_id": "oc_test", "binary": str(tmp_path / "missing.exe")}),
        encoding="utf-8",
    )

    outcome = feishu_push.auto_push(database)

    assert outcome is not None and outcome["sent"] is False and outcome["error"]


def test_config_needs_exactly_one_recipient(tmp_path: Path) -> None:
    path = tmp_path / feishu_push.CONFIG
    path.write_text(json.dumps({"chat_id": "oc_a", "user_id": "ou_b"}), encoding="utf-8")

    with pytest.raises(feishu_push.PushError):
        feishu_push.load_config(path)


def test_lark_cli_command_sends_as_bot_to_the_configured_chat() -> None:
    config = feishu_push.PushConfig(chat_id="oc_abc", binary="lark-cli.exe")

    command = feishu_push.lark_command(config, "## 标题\n正文", "jobagent-1")

    assert command[:4] == ["lark-cli.exe", "im", "+messages-send", "--as"]
    assert command[4] == "bot"
    assert command[command.index("--chat-id") + 1] == "oc_abc"
    assert command[command.index("--markdown") + 1] == "## 标题\n正文"
    assert command[command.index("--idempotency-key") + 1] == "jobagent-1"


def test_cli_push_dry_run_prints_the_message(tmp_path: Path) -> None:
    database, batch_id, _ = _asked(tmp_path)

    code, report = invoke("notify", "feishu", "--database", str(database), "--dry-run")

    assert code == 0 and isinstance(report, dict)
    assert batch_id in report["markdown"] and report["sent"] is False


def test_ask_and_patrol_finish_try_a_push_without_changing_their_output(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from jobagent.cli.app import app

    database, batch_id = drafted(tmp_path)
    (database.parent / feishu_push.CONFIG).write_text(
        json.dumps({"chat_id": "oc_test", "binary": str(tmp_path / "missing.exe")}),
        encoding="utf-8",
    )
    db = ["--database", str(database)]
    runner = CliRunner()

    asked = runner.invoke(app, ["outreach", "ask", batch_id, *db])
    started = runner.invoke(app, ["patrol", "record", *db, "--now", "2026-10-22T03:00:00+00:00"])
    check_id = json.loads(started.stdout)["check_id"]
    finished = runner.invoke(app, ["patrol", "finish", check_id, *db])

    for result in (asked, finished):
        assert result.exit_code == 0
        json.loads(result.stdout)
        assert '"feishu"' in result.stderr and "lark-cli could not run" in result.stderr


def test_custom_bot_webhook_is_a_recipient_of_its_own(tmp_path: Path) -> None:
    path = tmp_path / feishu_push.CONFIG
    path.write_text(json.dumps({"webhook": "https://open.feishu.cn/open-apis/bot/v2/hook/x"}),
                    encoding="utf-8")
    assert feishu_push.load_config(path).webhook

    path.write_text(json.dumps({"webhook": "http://example.com/hook"}), encoding="utf-8")
    with pytest.raises(feishu_push.PushError):
        feishu_push.load_config(path)


def test_webhook_payload_is_a_signed_markdown_card() -> None:
    config = feishu_push.PushConfig(webhook="https://open.feishu.cn/x", secret="s3cret")

    payload = feishu_push.webhook_payload(config, "**待审批**\n正文", timestamp=1761100000)

    assert payload["msg_type"] == "interactive"
    assert payload["card"]["elements"][0] == {"tag": "markdown", "content": "**待审批**\n正文"}
    assert payload["timestamp"] == "1761100000"
    assert payload["sign"] == "rrPEYBFdnykOQOgR17P6bWEl3Chu6XhBL7ArqMz2mCg="
    unsigned = feishu_push.webhook_payload(feishu_push.PushConfig(webhook="https://x"), "a")
    assert "sign" not in unsigned


def test_lark_cli_command_can_pick_a_named_profile() -> None:
    config = feishu_push.PushConfig(user_id="ou_me", binary="lark-cli.exe", profile="jobagent")

    command = feishu_push.lark_command(config, "正文", "jobagent-2")

    assert command[1:3] == ["--profile", "jobagent"]
    assert command[command.index("--user-id") + 1] == "ou_me"


def test_open_questions_get_one_approval_card_each(tmp_path: Path) -> None:
    database, batch_id, _ = _asked(tmp_path)
    cards: list[dict] = []

    def send_card(card: dict) -> str:
        cards.append(card)
        return f"om_{len(cards)}"

    first = feishu_push.send_cards(database, send_card)
    again = feishu_push.send_cards(database, send_card)

    assert first == ["om_1"] and again == []
    assert batch_id in cards[0]["header"]["subtitle"]["content"]
    report = feishu_push.push(database, send=Recorder(), now=NOW, cards=True)
    assert "审批卡片" in report["markdown"] and "方便聊聊吗" not in report["markdown"]


def test_card_commands_go_through_the_bot_and_the_profile() -> None:
    config = feishu_push.PushConfig(user_id="ou_me", binary="lark-cli.exe", profile="jobagent")

    send = feishu_push.card_command(config, {"schema": "2.0"})
    update = feishu_push.update_command(config, "tok", {"schema": "2.0"})
    listen = feishu_push.listen_command(config, hours=8)

    assert send[:3] == ["lark-cli.exe", "--profile", "jobagent"]
    assert send[send.index("--msg-type") + 1] == "interactive"
    assert json.loads(send[send.index("--content") + 1]) == {"schema": "2.0"}
    assert "/open-apis/interactive/v1/card/update" in update
    assert json.loads(update[update.index("--data") + 1])["token"] == "tok"
    assert listen[3:6] == ["event", "consume", "card.action.trigger"]
    assert listen[listen.index("--timeout") + 1] == "8h"


def test_a_patrol_report_is_pushed_word_for_word_once(tmp_path: Path) -> None:
    database, _, _ = _asked(tmp_path)
    feishu_push.push(database, send=Recorder(), now=NOW)
    report = feishu_push.report_update("PCHECK_1", "【新职位】Boss 列出 12 条，新增 3 条")
    send = Recorder()

    first = feishu_push.push(database, send=send, now=NOW, extra=[report])
    again = feishu_push.push(database, send=send, now=NOW, extra=[report])

    assert first["sent"] is True and again["sent"] is False
    assert "**巡检汇报**" in send.sent[0][0] and "新增 3 条" in send.sent[0][0]


def test_patrol_finish_pushes_the_report_file(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from jobagent.cli.app import app

    database, _ = drafted(tmp_path)
    (database.parent / feishu_push.CONFIG).write_text(
        json.dumps({"chat_id": "oc_test", "binary": str(tmp_path / "missing.exe")}),
        encoding="utf-8",
    )
    report = tmp_path / "report.md"
    report.write_text("本次无新职位、无新回复", encoding="utf-8")
    db = ["--database", str(database)]
    runner = CliRunner()
    started = runner.invoke(app, ["patrol", "record", *db, "--now", "2026-10-22T03:00:00+00:00"])
    check_id = json.loads(started.stdout)["check_id"]

    finished = runner.invoke(app, ["patrol", "finish", check_id, *db, "--report", str(report)])
    missing = runner.invoke(
        app, ["patrol", "finish", check_id, *db, "--report", str(tmp_path / "nope.md")]
    )

    assert finished.exit_code == 0 and "lark-cli could not run" in finished.stderr
    assert missing.exit_code == 1
