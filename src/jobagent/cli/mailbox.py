"""The Claude Code side of the Cowork mailbox: read, acknowledge, leave notes.

Cowork writes through the MCP bridge; these commands are how the main session
answers. A receipt says what happened to an entry. It never stands in for the
approval itself, which is still registered with `outreach approve`.
"""

import json
from pathlib import Path
from typing import Annotated, Never

import typer

from jobagent.bridge import mailbox
from jobagent.errors import JobAgentError

mailbox_app = typer.Typer(
    help="Mailbox between the Cowork front end and the main session.", no_args_is_help=True
)

MailboxOption = Annotated[
    Path, typer.Option("--mailbox", help="Private folder holding the mailbox files.")
]
DEFAULT_MAILBOX = Path("candidate/private")


def _emit(value: object) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _fail(error: JobAgentError) -> Never:
    typer.echo(
        json.dumps(
            {"error": {"code": error.code, "message": error.message, "details": error.details}},
            ensure_ascii=False,
        )
    )
    raise typer.Exit(1)


@mailbox_app.command("inbox")
def inbox(folder: MailboxOption = DEFAULT_MAILBOX) -> None:
    """Entries from Cowork that have no receipt yet, oldest first."""
    _emit(mailbox.unprocessed(folder))


@mailbox_app.command("ack")
def ack(
    entry_id: str,
    status: Annotated[str, typer.Option("--status", help="accepted|registered|done|rejected")],
    reason: Annotated[str, typer.Option("--reason", help="What was or will be done, and why.")],
    folder: MailboxOption = DEFAULT_MAILBOX,
) -> None:
    """Write the receipt Cowork reads for one inbox entry."""
    try:
        _emit(mailbox.acknowledge(folder, entry_id, status, reason))
    except JobAgentError as error:
        _fail(error)


@mailbox_app.command("notify")
def notify(
    text: str,
    ref: Annotated[
        list[str] | None, typer.Option("--ref", help="Batch, ask or job ids it is about.")
    ] = None,
    folder: MailboxOption = DEFAULT_MAILBOX,
) -> None:
    """Leave a note for Cowork, read through notes_from_claude_code."""
    try:
        _emit(mailbox.notify_cowork(folder, text, refs=ref))
    except JobAgentError as error:
        _fail(error)


@mailbox_app.command("register-session")
def register_session(
    role: str,
    session_id: str,
    name: Annotated[str, typer.Option("--name", help="Title the person sees.")] = "",
    folder: MailboxOption = DEFAULT_MAILBOX,
) -> None:
    """Record which session plays a role (claude_code or cowork)."""
    try:
        _emit(mailbox.register_session(folder, role, session_id, name=name))
    except JobAgentError as error:
        _fail(error)


@mailbox_app.command("peers")
def peers(folder: MailboxOption = DEFAULT_MAILBOX) -> None:
    """Show the registered sessions."""
    _emit(mailbox.peers(folder))
