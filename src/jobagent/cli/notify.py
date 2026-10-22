"""Carry ledger updates to the person's phone, and their card answers back.

Pushes only inform. A submitted approval card is registered under the same
rules as an answer in the chat; nothing here sends a greeting to anyone.
"""

import json
import subprocess
from pathlib import Path
from typing import Annotated, Never

import typer

from jobagent.bridge import feishu_approval, feishu_push

notify_app = typer.Typer(help="Push ledger updates to the person's phone.", no_args_is_help=True)

DatabaseOption = Annotated[Path, typer.Option("--database", help="Local SQLite path.")]
DEFAULT_DATABASE = Path(".jobagent/jobagent.sqlite3")
LISTEN_LOG = "feishu_listen.log"


def _fail(message: str) -> Never:
    typer.echo(json.dumps({"error": {"code": "push_failed", "message": message}},
                          ensure_ascii=False))
    raise typer.Exit(1)


@notify_app.callback()
def main() -> None:
    """Channels that carry updates out of the local ledger."""


@notify_app.command("feishu")
def feishu(
    database: DatabaseOption = DEFAULT_DATABASE,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Print the message; send and remember nothing.")
    ] = False,
) -> None:
    """Send one Feishu message when anything not pushed before is worth a look."""
    try:
        if dry_run:
            report = feishu_push.push(database, send=lambda *_: None, dry_run=True)
        else:
            config = feishu_push.load_config(database.parent / feishu_push.CONFIG)
            cards = not config.webhook
            report = feishu_push.push(
                database, send=feishu_push.sender_for(config), cards=cards
            )
            if cards:
                sent = feishu_push.send_cards(database, feishu_push.lark_card_sender(config))
                report["cards"] = sent
    except feishu_push.PushError as error:
        _fail(str(error))
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))


@notify_app.command("feishu-listen")
def feishu_listen(
    database: DatabaseOption = DEFAULT_DATABASE,
    hours: Annotated[int, typer.Option("--hours", min=1, max=24, help="Stop after this long.")] = 8,
) -> None:
    """Register approval cards the person submits in Feishu, one line per outcome."""
    try:
        config = feishu_push.load_config(database.parent / feishu_push.CONFIG)
    except feishu_push.PushError as error:
        _fail(str(error))
    owner = config.owner or config.user_id
    if config.webhook or not owner:
        _fail("Card answers need an app bot with user_id (or owner) in feishu_push.json.")
    update = feishu_push.lark_card_updater(config)
    send_card = feishu_push.lark_card_sender(config)
    log = (database.parent / LISTEN_LOG).open("a", encoding="utf-8")
    try:
        process = subprocess.Popen(
            feishu_push.listen_command(config, hours=hours),
            stdout=subprocess.PIPE,
            stderr=log,
            creationflags=feishu_push.NO_WINDOW,
        )
    except (OSError, feishu_push.PushError) as error:
        log.close()
        _fail(f"lark-cli could not start: {error}")
    assert process.stdout is not None
    try:
        for raw in process.stdout:
            line = raw.decode("utf-8", errors="replace")
            try:
                outcomes = feishu_approval.listen(
                    [line], database, owner=str(owner), update=update, send_card=send_card
                )
            except feishu_push.PushError as error:
                typer.echo(json.dumps({"error": str(error)}, ensure_ascii=False))
                continue
            for outcome in outcomes:
                typer.echo(json.dumps(
                    {"status": outcome.status, "lines": outcome.lines,
                     "approval_id": outcome.approval_id},
                    ensure_ascii=False,
                ), nl=True)
    finally:
        process.wait()
        log.close()
    if process.returncode != 0:
        tail = (database.parent / LISTEN_LOG).read_bytes()[-800:].decode("utf-8", "replace")
        _fail(f"lark-cli event consume exited {process.returncode}: {tail}")
