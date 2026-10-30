"""Transactions and append-only completion events for local workers."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from jobagent.errors import ContractValidationError, StorageError
from jobagent.schemas.worker import (
    WorkerEvent,
    WorkerEventAck,
    WorkerFetchReceipt,
    WorkerSendClaim,
    WorkerSendReceipt,
)
from jobagent.storage.database import Database

WorkerState = WorkerFetchReceipt | WorkerSendClaim | WorkerSendReceipt


class SqliteWorkerRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            with self.database.connect() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
        except sqlite3.Error as error:
            raise StorageError(
                "Worker transaction failed.", details={"operation": "worker"}
            ) from error

    @staticmethod
    def append_event(connection: sqlite3.Connection, event: WorkerEvent) -> None:
        connection.execute(
            "INSERT INTO worker_events (event_id, task_id, event_json, created_at) "
            "VALUES (?, ?, ?, ?)",
            (event.event_id, event.task_id, event.model_dump_json(), event.created_at.isoformat()),
        )

    def show(self, task_id: str) -> WorkerState | None:
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT receipt_json FROM worker_fetch_receipts WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is not None:
                return WorkerFetchReceipt.model_validate_json(row["receipt_json"])
            row = connection.execute(
                "SELECT claim_json, receipt_json FROM worker_send_claims WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if row is None:
                return None
            if row["receipt_json"] is not None:
                return WorkerSendReceipt.model_validate_json(row["receipt_json"])
            return WorkerSendClaim.model_validate_json(row["claim_json"])

    def events(self) -> list[WorkerEvent]:
        with self.transaction() as connection:
            rows = connection.execute(
                "SELECT e.event_json FROM worker_events e LEFT JOIN worker_event_acks a "
                "ON a.event_id = e.event_id WHERE a.event_id IS NULL "
                "ORDER BY e.created_at, e.event_id"
            ).fetchall()
        return [WorkerEvent.model_validate_json(row["event_json"]) for row in rows]

    def acknowledge(self, event_id: str, now: datetime) -> WorkerEventAck:
        with self.transaction() as connection:
            if (
                connection.execute(
                    "SELECT 1 FROM worker_events WHERE event_id = ?", (event_id,)
                ).fetchone()
                is None
            ):
                raise ContractValidationError("Worker event was not found.")
            connection.execute(
                "INSERT OR IGNORE INTO worker_event_acks (event_id, acknowledged_at) VALUES (?, ?)",
                (event_id, now.isoformat()),
            )
        return WorkerEventAck(event_id=event_id)
