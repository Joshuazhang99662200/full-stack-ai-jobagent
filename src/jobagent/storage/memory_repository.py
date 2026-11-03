"""Independent metadata-only sidecar; business databases never migrate here."""

import sqlite3
from contextlib import closing
from pathlib import Path

from jobagent.bridge.memory_sources import private_path
from jobagent.errors import ContractValidationError
from jobagent.memory.selection import snapshot_identity
from jobagent.schemas.memory import MemorySnapshot


class MemoryRepository:
    def __init__(self, path: Path) -> None:
        self.path = private_path(path)

    def _read(self) -> sqlite3.Connection:
        connection = sqlite3.connect(private_path(self.path).as_uri() + "?mode=ro", uri=True)
        connection.execute("PRAGMA query_only = ON")
        self._check(connection)
        return connection

    @staticmethod
    def _check(connection: sqlite3.Connection) -> None:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if version != 1 or tables != {"memory_snapshots"}:
            raise ContractValidationError("Not a supported memory metadata sidecar.")

    def count(self, candidate_id: str) -> int:
        if not private_path(self.path).exists():
            return 0
        with closing(self._read()) as connection:
            return int(
                connection.execute(
                    "SELECT count(*) FROM memory_snapshots WHERE candidate_id=?", (candidate_id,)
                ).fetchone()[0]
            )

    def get(self, snapshot_id: str, candidate_id: str) -> MemorySnapshot:
        if not private_path(self.path).exists():
            raise ContractValidationError("Memory sidecar does not exist.")
        with closing(self._read()) as connection:
            row = connection.execute(
                "SELECT snapshot_json FROM memory_snapshots WHERE snapshot_id=? AND candidate_id=?",
                (snapshot_id, candidate_id),
            ).fetchone()
        if row is None:
            raise ContractValidationError("Snapshot not found for this candidate.")
        snapshot = MemorySnapshot.model_validate_json(row[0])
        if (
            snapshot.candidate_id != candidate_id
            or snapshot.snapshot_id != snapshot_id
            or snapshot_identity(snapshot) != snapshot_id
        ):
            raise ContractValidationError("Memory snapshot ownership or identity is invalid.")
        return snapshot

    def save(self, snapshot: MemorySnapshot) -> MemorySnapshot:
        if snapshot_identity(snapshot) != snapshot.snapshot_id:
            raise ContractValidationError("Memory snapshot identity is invalid.")
        path = private_path(self.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if not tables and version == 0:
                connection.execute(
                    "CREATE TABLE memory_snapshots (snapshot_id TEXT PRIMARY KEY, "
                    "candidate_id TEXT NOT NULL, snapshot_json TEXT NOT NULL)"
                )
                connection.execute("PRAGMA user_version = 1")
            else:
                self._check(connection)
            old = connection.execute(
                "SELECT snapshot_json FROM memory_snapshots WHERE snapshot_id=?",
                (snapshot.snapshot_id,),
            ).fetchone()
            if old:
                prior = MemorySnapshot.model_validate_json(old[0])
                if prior.model_dump(exclude={"compiled_at"}) != snapshot.model_dump(
                    exclude={"compiled_at"}
                ):
                    raise ContractValidationError("Immutable memory snapshot conflicts.")
                return prior
            connection.execute(
                "INSERT INTO memory_snapshots VALUES (?, ?, ?)",
                (snapshot.snapshot_id, snapshot.candidate_id, snapshot.model_dump_json()),
            )
        return snapshot
