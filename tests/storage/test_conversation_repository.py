# ruff: noqa: RUF001  -- Chinese messages carry full-width punctuation by design.
from pathlib import Path

import pytest

from jobagent.errors import StorageError
from jobagent.schemas.conversation import (
    ConversationStage,
    MessageLevel,
    ReplyDraft,
    ReplyKind,
    ReplyResult,
)
from jobagent.storage.conversation_repository import SqliteConversationRepository
from jobagent.storage.database import Database
from tests.conversation.test_service import NOW, SERVICE, inbound, opened


def repository(tmp_path: Path) -> SqliteConversationRepository:
    database = Database(tmp_path / "jobagent.sqlite3")
    database.migrate()
    return SqliteConversationRepository(database)


def test_conversation_and_events_round_trip_in_order(tmp_path: Path) -> None:
    store = repository(tmp_path)
    conversation, events = opened()
    store.save_conversation(conversation)
    store.append_events(events)
    store.append_events(SERVICE.receive(conversation, events, inbound(), now=NOW))

    assert store.get_conversation(conversation.conversation_id) == conversation
    stored = store.list_events(conversation.conversation_id)
    assert [event.seq for event in stored] == [1, 2, 3]
    assert SERVICE.stage(stored) is ConversationStage.REPLIED
    assert [c.conversation_id for c in store.list_conversations()] == [conversation.conversation_id]


def test_events_must_continue_the_sequence(tmp_path: Path) -> None:
    store = repository(tmp_path)
    conversation, events = opened()
    store.save_conversation(conversation)
    store.append_events(events)
    first = SERVICE.receive(conversation, events, inbound(), now=NOW)
    store.append_events(first)

    # A second writer working from the old event list collides instead of interleaving.
    with pytest.raises(StorageError):
        store.append_events(SERVICE.receive(conversation, events, inbound("还在吗？"), now=NOW))
    assert not hasattr(store, "delete_event") and not hasattr(store, "update_event")


def test_reply_failures_are_reported_per_platform(tmp_path: Path) -> None:
    store = repository(tmp_path)
    conversation, events = opened()
    store.save_conversation(conversation)
    store.append_events(events)
    replied = events + SERVICE.receive(conversation, events, inbound(), now=NOW)
    store.append_events(replied[len(events) :])
    target = replied[1].event_id
    ask = SERVICE.draft_reply(
        conversation,
        replied,
        ReplyDraft(kind=ReplyKind.ANSWER, text="您好，在的。", in_reply_to=target),
        now=NOW,
    )
    store.save_ask(ask)
    approval = SERVICE.approve_reply(conversation, replied, ask, answer="发", now=NOW)
    store.append_events([approval])
    failed = SERVICE.record_reply(
        conversation, [*replied, approval], result=ReplyResult.FAILED, reason="未送达", now=NOW
    )
    store.append_events(failed)

    assert store.get_ask(ask.ask_id) == ask
    assert store.reply_failures() == [(conversation.platform, NOW)]
    assert inbound().level is MessageLevel.L1


def test_only_the_first_sighting_of_each_receipt_is_kept(tmp_path: Path) -> None:
    from datetime import timedelta

    from jobagent.schemas.patrol import ConversationReceipt

    store = repository(tmp_path)
    conversation, events = opened()
    store.save_conversation(conversation)
    store.append_events(events)
    cid = conversation.conversation_id

    def receipt(status: str, at_hours: int, snapshot: str) -> ConversationReceipt:
        return ConversationReceipt(
            conversation_id=cid,
            status=status,  # type: ignore[arg-type]
            observed_at=NOW + timedelta(hours=at_hours),
            snapshot_id=snapshot,
        )

    assert store.record_receipts([receipt("delivered", 0, "PSNAP_A")]) == 1
    assert (
        store.record_receipts([receipt("delivered", 1, "PSNAP_B"), receipt("read", 1, "PSNAP_B")])
        == 1
    )

    kept = store.receipts()
    assert [(r.status, r.snapshot_id) for r in kept] == [
        ("delivered", "PSNAP_A"),
        ("read", "PSNAP_B"),
    ]
