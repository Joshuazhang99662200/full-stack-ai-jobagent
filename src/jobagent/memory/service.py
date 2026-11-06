"""Organize inventory and context through ports; never call a model or write business state."""

from datetime import UTC, datetime

from jobagent.digest import canonical_digest
from jobagent.errors import ContractValidationError
from jobagent.memory.ports import SnapshotStore, SourceReader
from jobagent.memory.selection import select
from jobagent.schemas.memory import (
    MemoryConfig,
    MemoryContextBundle,
    MemoryRead,
    MemorySnapshot,
    MemoryStatus,
)


def _bound(bundle: MemoryContextBundle) -> MemoryContextBundle:
    bundle.context_digest = canonical_digest(
        bundle.model_dump(mode="json", exclude={"context_digest"})
    )
    return bundle


class MemoryService:
    def __init__(self, config: MemoryConfig, reader: SourceReader, store: SnapshotStore) -> None:
        self.config = MemoryConfig.model_validate(config.model_dump())
        self.reader = reader
        self.store = store
        if any(s.candidate_id != config.candidate_id for s in config.sources):
            raise ContractValidationError("Memory sources belong to another candidate.")

    def _read(self) -> list[MemoryRead]:
        reads = [self.reader.read(source) for source in self.config.sources]
        for read in reads:
            if read.source.candidate_id != self.config.candidate_id or any(
                item.candidate_id != self.config.candidate_id for item in read.items
            ):
                raise ContractValidationError("Memory source records belong to another candidate.")
        return reads

    def status(self) -> MemoryStatus:
        return MemoryStatus(
            candidate_id=self.config.candidate_id,
            sources=[r.source for r in self._read()],
            snapshot_count=self.store.count(self.config.candidate_id),
        )

    def compile(self) -> MemorySnapshot:
        sources = [r.source for r in self._read()]
        config_digest = canonical_digest(self.config.model_dump(mode="json"))
        identity = canonical_digest(
            {
                "candidate_id": self.config.candidate_id,
                "config_digest": config_digest,
                "adapter_version": "memory.p1.v1",
                "sources": [s.model_dump(mode="json") for s in sources],
            }
        )
        return self.store.save(
            MemorySnapshot(
                snapshot_id=identity,
                candidate_id=self.config.candidate_id,
                config_digest=config_digest,
                compiled_at=datetime.now(UTC),
                sources=sources,
            )
        )

    def context(
        self, snapshot_id: str, *, task: str, candidate_id: str, job_id: str | None = None
    ) -> MemoryContextBundle:
        if candidate_id != self.config.candidate_id:
            raise ContractValidationError("Memory context belongs to another candidate.")
        bundle = MemoryContextBundle(
            candidate_id=candidate_id,
            snapshot_id=snapshot_id,
            task=task,
            job_id=job_id,
            status="blocked",
            usable=False,
        )
        if task not in {"search", "greeting"}:
            return _bound(
                bundle.model_copy(
                    update={"status": "not_integrated", "diagnostics": ["task_not_integrated"]}
                )
            )
        snapshot = self.store.get(snapshot_id, candidate_id)
        if snapshot.config_digest != canonical_digest(self.config.model_dump(mode="json")):
            bundle.diagnostics.append("config_changed")
            return _bound(bundle)
        reads = self._read()
        bundle.sources = [r.source for r in reads]
        # Only supported context sources are dependencies; inventory does not grant rules.
        relevant = (
            {"preference_memory", "confirmed_rules"}
            if task == "greeting"
            else {"preference_memory"}
        )
        expected = {s.source_id: s for s in snapshot.sources}
        usable = False
        candidates = []
        for read in reads:
            source = read.source
            if source.kind not in relevant:
                continue
            if source != expected.get(source.source_id):
                bundle.diagnostics.append("source_changed")
                return _bound(bundle)
            if source.state not in {"ready", "empty"}:
                bundle.diagnostics.append("source_unavailable:" + source.source_id)
                return _bound(bundle)
            usable = True
            candidates.extend(read.items)
        bundle.items, excluded = select(candidates, task=task, job_id=job_id)
        bundle.diagnostics.extend(excluded)
        if "rule_conflict" in excluded:
            return _bound(bundle)
        bundle.usable = usable
        bundle.status = "ready" if usable else "blocked"
        if not usable:
            bundle.diagnostics.append("no_supported_source")
        return _bound(bundle)
