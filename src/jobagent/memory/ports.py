"""Infrastructure ports for source inventory and immutable snapshots."""

from typing import Protocol

from jobagent.schemas.memory import MemoryRead, MemorySnapshot, MemorySource


class SourceReader(Protocol):
    def read(self, source: MemorySource) -> MemoryRead: ...


class SnapshotStore(Protocol):
    def save(self, snapshot: MemorySnapshot) -> MemorySnapshot: ...

    def get(self, snapshot_id: str, candidate_id: str) -> MemorySnapshot: ...

    def count(self, candidate_id: str) -> int: ...
