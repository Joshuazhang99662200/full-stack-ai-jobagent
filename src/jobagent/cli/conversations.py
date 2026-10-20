"""JSON-first commands for conversations after a first greeting.

The host reads chats in the person's own browser and reports each recruiter
message with `inbound`. Replies are drafted by the host, asked, answered by a
person, released by `reply-gate`, sent by the host and recorded. Nothing here
reads or clicks a page.
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Never

import typer
from pydantic import ValidationError

from jobagent.conversation.service import (
    UNKNOWN_TITLES,
    ConversationService,
    company_key,
    is_halted_today,
    screened_term,
)
from jobagent.errors import ApprovalRequiredError, ContractValidationError, JobAgentError
from jobagent.schemas.common import ContractModel
from jobagent.schemas.conversation import (
    Conversation,
    ConversationEvent,
    ConversationStage,
    InboundMessage,
    MessageLevel,
    ReplyDraft,
    ReplyGateDecision,
    ReplyKind,
    ReplyResult,
)
from jobagent.schemas.job_intelligence import CandidateFilterContext
from jobagent.schemas.optimizer import ResumeVariant
from jobagent.schemas.outreach import OutreachResult
from jobagent.storage.conversation_repository import SqliteConversationRepository
from jobagent.storage.database import Database
from jobagent.storage.outreach_repository import SqliteOutreachRepository

DEFAULT_DATABASE = Path(".jobagent/jobagent.sqlite3")
DatabaseOption = Annotated[Path, typer.Option("--database", help="Local SQLite path.")]
SessionOption = Annotated[str, typer.Option("--session", help="The sending session's id.")]
SERVICE = ConversationService()

conversations_app = typer.Typer(
    help="Track each job's conversation: messages, stage, approved replies and resume.",
    no_args_is_help=True,
)


def _emit(value: ContractModel | dict[str, object] | list[object]) -> None:
    if isinstance(value, ContractModel):
        typer.echo(value.model_dump_json(indent=2))
    else:
        typer.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _fail(error: JobAgentError) -> Never:
    typer.echo(
        json.dumps(
            {"error": {"code": error.code, "message": error.message, "details": error.details}},
            ensure_ascii=False,
        )
    )
    raise typer.Exit(code=1)


def _stores(path: Path) -> tuple[SqliteConversationRepository, SqliteOutreachRepository]:
    path.parent.mkdir(parents=True, exist_ok=True)
    database = Database(path)
    database.migrate()
    return SqliteConversationRepository(database), SqliteOutreachRepository(database)


def _load(
    store: SqliteConversationRepository, conversation_id: str
) -> tuple[Conversation, list[ConversationEvent]]:
    conversation = store.get_conversation(conversation_id)
    if conversation is None:
        raise ContractValidationError(
            "Conversation was not found.", details={"conversation_id": conversation_id}
        )
    return conversation, store.list_events(conversation_id)


def _state(conversation: Conversation, events: list[ConversationEvent]) -> dict[str, object]:
    stage = SERVICE.stage(events)
    return {
        "conversation_id": conversation.conversation_id,
        "platform": conversation.platform,
        "company": conversation.company,
        "title": conversation.title,
        "job_id": conversation.job_id,
        "origin": conversation.origin,
        "stage": None if stage is None else stage.value,
        "last_event": events[-1].kind.value if events else None,
    }


def _append(
    store: SqliteConversationRepository,
    conversation: Conversation,
    events: list[ConversationEvent],
    new: list[ConversationEvent],
) -> None:
    store.append_events(new)
    _emit(_state(conversation, [*events, *new]))


@conversations_app.command("sync-outreach")
def sync_outreach(database: DatabaseOption = DEFAULT_DATABASE) -> None:
    """Open a conversation for every greeting that reached a recruiter."""
    try:
        store, outreach = _stores(database)
        opened: list[dict[str, object]] = []
        for audit in outreach.list_audits():
            if audit.result not in (OutreachResult.SENT, OutreachResult.DUPLICATE_FOUND):
                continue
            batch = outreach.get_batch(audit.batch_id)
            item = (
                next((i for i in batch.items if i.number == audit.number), None) if batch else None
            )
            if item is None:
                continue
            conversation, event = SERVICE.open_from_outreach(audit, item, now=datetime.now(UTC))
            if store.get_conversation(conversation.conversation_id) is not None:
                continue
            store.save_conversation(conversation)
            store.append_events([event])
            opened.append(_state(conversation, [event]))
        _emit({"opened": opened})
    except JobAgentError as error:
        _fail(error)


def _refuse_duplicate(store: SqliteConversationRepository, platform: str, company: str) -> None:
    key = company_key(company)
    existing = [
        c.conversation_id
        for c in store.list_conversations()
        if c.platform == platform and company_key(c.company) == key
    ]
    if existing:
        raise ContractValidationError(
            "A conversation with this recruiter is already logged; record new messages there.",
            details={"existing": existing},
        )


@conversations_app.command("open")
def open_inbound(
    platform: Annotated[str, typer.Option("--platform")],
    company: Annotated[str, typer.Option("--company")],
    title: Annotated[str, typer.Option("--title")],
    filter_context: Annotated[
        Path,
        typer.Option("--filter-context", help="CandidateFilterContext JSON; its exclusions apply."),
    ],
    database: DatabaseOption = DEFAULT_DATABASE,
    job_id: Annotated[str | None, typer.Option("--job-id")] = None,
) -> None:
    """Open a conversation a recruiter started, screened against the person's exclusions."""
    try:
        context = CandidateFilterContext.model_validate_json(
            filter_context.read_text(encoding="utf-8")
        )
        store, _ = _stores(database)
        conversation, event = SERVICE.open_inbound(
            platform=platform,
            company=company,
            title=title,
            job_id=job_id,
            excluded_terms=context.excluded_role_terms,
            now=datetime.now(UTC),
            exceptions=context.excluded_role_exceptions,
        )
        _refuse_duplicate(store, platform, company)
        store.save_conversation(conversation)
        store.append_events([event])
        term = screened_term(
            title, company, context.excluded_role_terms, context.excluded_role_exceptions
        )
        _emit(
            {
                **_state(conversation, [event]),
                "screen": {
                    "excluded": term is not None,
                    "term": term,
                    "title_unknown": title.strip() in UNKNOWN_TITLES,
                },
            }
        )
    except OSError as error:
        _fail(ContractValidationError(f"Filter context could not be read: {error}"))
    except (JobAgentError, ValidationError) as error:
        _fail(error if isinstance(error, JobAgentError) else ContractValidationError(str(error)))


@conversations_app.command("adopt")
def adopt(
    platform: Annotated[str, typer.Option("--platform")],
    company: Annotated[str, typer.Option("--company")],
    title: Annotated[str, typer.Option("--title")],
    database: DatabaseOption = DEFAULT_DATABASE,
    job_id: Annotated[str | None, typer.Option("--job-id")] = None,
    replied: Annotated[bool, typer.Option("--replied", help="The recruiter has answered.")] = False,
) -> None:
    """Log a conversation the person started on their own, apart from outreach."""
    try:
        store, _ = _stores(database)
        conversation, event = SERVICE.adopt_self(
            platform=platform,
            company=company,
            title=title,
            job_id=job_id,
            replied=replied,
            now=datetime.now(UTC),
        )
        _refuse_duplicate(store, platform, company)
        store.save_conversation(conversation)
        _append(store, conversation, [], [event])
    except (JobAgentError, ValidationError) as error:
        _fail(error if isinstance(error, JobAgentError) else ContractValidationError(str(error)))


@conversations_app.command("inbound")
def inbound(
    conversation_id: str,
    text: Annotated[str, typer.Option("--text", help="The recruiter's words, verbatim.")],
    level: Annotated[MessageLevel, typer.Option("--level")],
    database: DatabaseOption = DEFAULT_DATABASE,
    asks_resume: Annotated[bool, typer.Option("--asks-resume")] = False,
    interview_invite: Annotated[bool, typer.Option("--interview-invite")] = False,
    declined: Annotated[bool, typer.Option("--declined")] = False,
) -> None:
    """Record a recruiter's message and the stage change its level and flags imply."""
    try:
        store, _ = _stores(database)
        conversation, events = _load(store, conversation_id)
        now = datetime.now(UTC)
        message = InboundMessage(
            text=text,
            level=level,
            asks_resume=asks_resume,
            interview_invite=interview_invite,
            declined=declined,
            received_at=now,
        )
        _append(
            store, conversation, events, SERVICE.receive(conversation, events, message, now=now)
        )
    except JobAgentError as error:
        _fail(error)


@conversations_app.command("transition")
def transition(
    conversation_id: str,
    to: Annotated[ConversationStage, typer.Option("--to")],
    reason: Annotated[str, typer.Option("--reason")],
    database: DatabaseOption = DEFAULT_DATABASE,
) -> None:
    """Move a conversation along an allowed edge, with a reason."""
    try:
        store, _ = _stores(database)
        conversation, events = _load(store, conversation_id)
        event = SERVICE.transition(conversation, events, to, reason=reason, now=datetime.now(UTC))
        _append(store, conversation, events, [event])
    except JobAgentError as error:
        _fail(error)


@conversations_app.command("ask-intent")
def ask_intent(conversation_id: str, database: DatabaseOption = DEFAULT_DATABASE) -> None:
    """Ask the person whether to pursue this job. Asking confirms nothing."""
    try:
        store, _ = _stores(database)
        conversation, events = _load(store, conversation_id)
        question = SERVICE.ask_intent(conversation, events, now=datetime.now(UTC))
        store.save_ask(question)
        _emit(question)
    except JobAgentError as error:
        _fail(error)


@conversations_app.command("confirm-intent")
def confirm_intent(
    conversation_id: str,
    request: Annotated[str, typer.Option("--request", help="The CASK_* that was put first.")],
    answer: Annotated[str, typer.Option("--answer", help="The person's own words, verbatim.")],
    database: DatabaseOption = DEFAULT_DATABASE,
) -> None:
    """Record the person's answer to the intent question."""
    try:
        store, _ = _stores(database)
        conversation, events = _load(store, conversation_id)
        question = store.get_ask(request)
        if question is None:
            raise ApprovalRequiredError(
                "Intent must answer a question that was posed first.",
                details={"conversation_id": conversation_id, "ask_id": request},
            )
        event = SERVICE.confirm_intent(
            conversation, events, question, answer=answer, now=datetime.now(UTC)
        )
        _append(store, conversation, events, [event])
    except JobAgentError as error:
        _fail(error)


@conversations_app.command("attach-resume")
def attach_resume(
    conversation_id: str,
    variant_path: Annotated[Path, typer.Argument(help="Verified ResumeVariant JSON.")],
    pdf_path: Annotated[Path, typer.Argument(help="The rendered file that will be sent.")],
    database: DatabaseOption = DEFAULT_DATABASE,
) -> None:
    """Attach a verified variant for this job, bound to the exact file's digest."""
    try:
        store, _ = _stores(database)
        conversation, events = _load(store, conversation_id)
        try:
            variant = ResumeVariant.model_validate_json(variant_path.read_bytes())
            pdf_digest = "sha256:" + hashlib.sha256(pdf_path.read_bytes()).hexdigest()
        except (OSError, ValidationError):
            raise ContractValidationError(
                "The variant or resume file could not be read.",
                details={"variant": variant_path.name, "file": pdf_path.name},
            ) from None
        event = SERVICE.attach_resume(
            conversation, events, variant, pdf_digest=pdf_digest, now=datetime.now(UTC)
        )
        _append(store, conversation, events, [event])
    except JobAgentError as error:
        _fail(error)


@conversations_app.command("draft-reply")
def draft_reply(
    conversation_id: str,
    kind: Annotated[ReplyKind, typer.Option("--kind")],
    text: Annotated[str, typer.Option("--text")],
    database: DatabaseOption = DEFAULT_DATABASE,
) -> None:
    """Check a host-drafted reply and turn it into a question for the person."""
    try:
        store, _ = _stores(database)
        conversation, events = _load(store, conversation_id)
        latest = next((e for e in reversed(events) if e.kind.value == "inbound"), None)
        draft = ReplyDraft(
            kind=kind,
            text=text,
            in_reply_to=None if kind is ReplyKind.FOLLOW_UP or latest is None else latest.event_id,
        )
        question = SERVICE.draft_reply(conversation, events, draft, now=datetime.now(UTC))
        store.save_ask(question)
        _emit(question)
    except JobAgentError as error:
        _fail(error)


@conversations_app.command("approve-reply")
def approve_reply(
    conversation_id: str,
    request: Annotated[str, typer.Option("--request", help="The CASK_* that was put first.")],
    answer: Annotated[str, typer.Option("--answer", help="The person's own words, verbatim.")],
    database: DatabaseOption = DEFAULT_DATABASE,
) -> None:
    """Record the person's approval of one reply."""
    try:
        store, _ = _stores(database)
        conversation, events = _load(store, conversation_id)
        question = store.get_ask(request)
        if question is None or question.subject != "reply":
            raise ApprovalRequiredError(
                "A reply must answer a question that was posed first.",
                details={"conversation_id": conversation_id, "ask_id": request},
            )
        event = SERVICE.approve_reply(
            conversation, events, question, answer=answer, now=datetime.now(UTC)
        )
        _append(store, conversation, events, [event])
    except JobAgentError as error:
        _fail(error)


def _gate(
    store: SqliteConversationRepository,
    outreach: SqliteOutreachRepository,
    conversation: Conversation,
    events: list[ConversationEvent],
    session: str,
) -> ReplyGateDecision:
    now = datetime.now(UTC)
    held = outreach.holds_lease(conversation.platform, session, now=now)
    halted = is_halted_today(
        conversation.platform,
        now,
        outreach_audits=outreach.list_audits(),
        reply_failures=store.reply_failures(),
    )
    return SERVICE.reply_gate(conversation, events, lease_held=held, platform_halted=halted)


@conversations_app.command("reply-gate")
def reply_gate(
    conversation_id: str,
    session: SessionOption,
    database: DatabaseOption = DEFAULT_DATABASE,
) -> None:
    """Say whether the approved reply may be sent now."""
    try:
        store, outreach = _stores(database)
        conversation, events = _load(store, conversation_id)
        _emit(_gate(store, outreach, conversation, events, session))
    except JobAgentError as error:
        _fail(error)


@conversations_app.command("record-reply")
def record_reply(
    conversation_id: str,
    result: Annotated[ReplyResult, typer.Option("--result")],
    session: SessionOption,
    database: DatabaseOption = DEFAULT_DATABASE,
    reason: Annotated[str | None, typer.Option("--reason")] = None,
    file: Annotated[
        Path | None, typer.Option("--file", help="For a resume: the file actually uploaded.")
    ] = None,
) -> None:
    """Record what happened to the approved reply. Failures halt the platform today."""
    try:
        store, outreach = _stores(database)
        conversation, events = _load(store, conversation_id)
        if not outreach.holds_lease(conversation.platform, session, now=datetime.now(UTC)):
            raise ContractValidationError(
                "Only the session holding the platform lease may record a send.",
                details={"platform": conversation.platform, "reason": "lease_not_held"},
            )
        attachment: str | None = None
        if file is not None:
            try:
                attachment = "sha256:" + hashlib.sha256(file.read_bytes()).hexdigest()
            except OSError:
                raise ContractValidationError(
                    "The uploaded file could not be read.", details={"file": file.name}
                ) from None
        new = SERVICE.record_reply(
            conversation,
            events,
            result=result,
            reason=reason,
            now=datetime.now(UTC),
            attachment_digest=attachment,
        )

        _append(store, conversation, events, new)
    except JobAgentError as error:
        _fail(error)


@conversations_app.command("due")
def due(database: DatabaseOption = DEFAULT_DATABASE) -> None:
    """List what needs doing: follow-ups, silences, resumes and messages for the person."""
    try:
        store, _ = _stores(database)
        loaded = {
            c.conversation_id: (c, store.list_events(c.conversation_id))
            for c in store.list_conversations()
        }
        items = SERVICE.due(loaded, now=datetime.now(UTC))
        _emit([item.model_dump(mode="json") for item in items])
    except JobAgentError as error:
        _fail(error)


@conversations_app.command("show")
def show(conversation_id: str, database: DatabaseOption = DEFAULT_DATABASE) -> None:
    """Show one conversation's stage and full event log."""
    try:
        store, _ = _stores(database)
        conversation, events = _load(store, conversation_id)
        _emit(
            {
                **_state(conversation, events),
                "events": [event.model_dump(mode="json") for event in events],
            }
        )
    except JobAgentError as error:
        _fail(error)


@conversations_app.command("list")
def list_conversations(
    database: DatabaseOption = DEFAULT_DATABASE,
    origin: Annotated[
        str | None, typer.Option("--origin", help="outreach, inbound or self.")
    ] = None,
) -> None:
    """List conversations with their current stage, optionally from one origin only."""
    try:
        store, _ = _stores(database)
        _emit(
            [
                _state(c, store.list_events(c.conversation_id))
                for c in store.list_conversations()
                if origin is None or c.origin == origin
            ]
        )
    except JobAgentError as error:
        _fail(error)
