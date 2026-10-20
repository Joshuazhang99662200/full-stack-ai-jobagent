"""SQLite adapter for conversations and their append-only event log."""

import sqlite3
from collections.abc import Sequence
from datetime import datetime
from typing import Never

from jobagent.errors import StorageError
from jobagent.schemas.conversation import (
    Conversation,
    ConversationAsk,
    ConversationEvent,
    EventKind,
    ReplyResult,
)
from jobagent.storage.database import Database

_HALTING_REPLIES = (ReplyResult.FAILED.value, ReplyResult.INTERVENTION.value)


class SqliteConversationRepository:
    """Store conversations. Events are only ever appended, in sequence."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def save_conversation(self, conversation: Conversation) -> None:
        self._write(
            "save conversation",
            "INSERT OR IGNORE INTO conversations "
            "(conversation_id, platform, job_id, conversation_json, opened_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                conversation.conversation_id,
                conversation.platform,
                conversation.job_id,
                conversation.model_dump_json(),
                conversation.opened_at.isoformat(),
            ),
        )

    def get_conversation(self, conversation_id: str) -> Conversation | None:
        rows = self._read(
            "read conversation",
            "SELECT conversation_json AS body FROM conversations WHERE conversation_id = ?",
            (conversation_id,),
        )
        return Conversation.model_validate_json(rows[0]["body"]) if rows else None

    def list_conversations(self) -> list[Conversation]:
        rows = self._read(
            "list conversations",
            "SELECT conversation_json AS body FROM conversations "
            "ORDER BY opened_at, conversation_id",
            (),
        )
        return [Conversation.model_validate_json(row["body"]) for row in rows]

    def append_events(self, events: Sequence[ConversationEvent]) -> None:
        """Append events that continue the stored sequence, all or nothing."""
        if not events:
            return
        try:
            with self.database.connect() as connection, connection:
                for event in events:
                    row = connection.execute(
                        "SELECT MAX(seq) AS highest FROM conversation_events "
                        "WHERE conversation_id = ?",
                        (event.conversation_id,),
                    ).fetchone()
                    expected = (row["highest"] or 0) + 1
                    if event.seq != expected:
                        raise StorageError(
                            "The conversation changed since these events were prepared.",
                            details={
                                "conversation_id": event.conversation_id,
                                "expected_seq": expected,
                                "got_seq": event.seq,
                            },
                        )
                    connection.execute(
                        "INSERT INTO conversation_events "
                        "(event_id, conversation_id, seq, kind, event_json, recorded_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            event.event_id,
                            event.conversation_id,
                            event.seq,
                            event.kind.value,
                            event.model_dump_json(),
                            event.recorded_at.isoformat(),
                        ),
                    )
        except sqlite3.Error as error:
            self._raise("append conversation events", error)

    def list_events(self, conversation_id: str) -> list[ConversationEvent]:
        rows = self._read(
            "list conversation events",
            "SELECT event_json AS body FROM conversation_events "
            "WHERE conversation_id = ? ORDER BY seq",
            (conversation_id,),
        )
        return [ConversationEvent.model_validate_json(row["body"]) for row in rows]

    def save_ask(self, ask: ConversationAsk) -> None:
        self._write(
            "save conversation question",
            "INSERT OR REPLACE INTO conversation_asks (ask_id, conversation_id, ask_json) "
            "VALUES (?, ?, ?)",
            (ask.ask_id, ask.conversation_id, ask.model_dump_json()),
        )

    def get_ask(self, ask_id: str) -> ConversationAsk | None:
        rows = self._read(
            "read conversation question",
            "SELECT ask_json AS body FROM conversation_asks WHERE ask_id = ?",
            (ask_id,),
        )
        return ConversationAsk.model_validate_json(rows[0]["body"]) if rows else None

    def reply_failures(self) -> list[tuple[str, datetime]]:
        """Every failed or intervened reply, by platform, for same-day halts."""
        rows = self._read(
            "list reply failures",
            "SELECT c.platform AS platform, e.event_json AS body FROM conversation_events e "
            "JOIN conversations c ON c.conversation_id = e.conversation_id "
            "WHERE e.kind = ? ORDER BY e.recorded_at",
            (EventKind.REPLY_RESULT.value,),
        )
        failures: list[tuple[str, datetime]] = []
        for row in rows:
            event = ConversationEvent.model_validate_json(row["body"])
            if event.result is not None and event.result.value in _HALTING_REPLIES:
                failures.append((str(row["platform"]), event.recorded_at))
        return failures

    def latest_recruiter_message_at(self) -> datetime | None:
        """When a recruiter last wrote: an inbound message, or a conversation they opened."""
        rows = self._read(
            "read latest recruiter message",
            "SELECT e.event_json AS body FROM conversation_events e "
            "JOIN conversations c ON c.conversation_id = e.conversation_id "
            "WHERE e.kind = ? "
            "OR (e.kind = ? AND json_extract(c.conversation_json, '$.origin') = ?) "
            "ORDER BY e.recorded_at DESC LIMIT 1",
            (EventKind.INBOUND.value, EventKind.OPENED.value, "inbound"),
        )
        if not rows:
            return None
        return ConversationEvent.model_validate_json(rows[0]["body"]).recorded_at

    def _write(self, operation: str, sql: str, parameters: tuple[object, ...]) -> None:
        try:
            with self.database.connect() as connection, connection:
                connection.execute(sql, parameters)
        except sqlite3.Error as error:
            self._raise(operation, error)

    def _read(self, operation: str, sql: str, parameters: tuple[object, ...]) -> list[sqlite3.Row]:
        try:
            with self.database.connect() as connection:
                return list(connection.execute(sql, parameters).fetchall())
        except sqlite3.Error as error:
            self._raise(operation, error)

    def _raise(self, operation: str, error: sqlite3.Error) -> Never:
        raise StorageError(
            f"Could not {operation}.",
            details={"path": str(self.database.path), "operation": operation},
        ) from error
