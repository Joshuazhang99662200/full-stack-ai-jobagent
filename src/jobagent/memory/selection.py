"""Deterministic scope filtering; free-text conditions are not executable predicates."""

from jobagent.digest import canonical_digest
from jobagent.schemas.memory import MemoryItem, MemorySnapshot


def snapshot_identity(snapshot: MemorySnapshot) -> str:
    return canonical_digest(
        {
            "candidate_id": snapshot.candidate_id,
            "config_digest": snapshot.config_digest,
            "adapter_version": snapshot.adapter_version,
            "sources": [s.model_dump(mode="json") for s in snapshot.sources],
        }
    )


def select(
    items: list[MemoryItem], *, task: str, job_id: str | None
) -> tuple[list[MemoryItem], list[str]]:
    selected = []
    diagnostics = []
    for item in items:
        if item.task != task:
            continue
        if item.scope in {"role", "unsupported"}:
            diagnostics.append("scope_not_integrated:" + item.source_id + ":" + item.item_id)
        elif item.scope == "general" or (job_id is not None and item.job_id == job_id):
            selected.append(item)
    # Contradictory semantics cannot be judged without a separate supported reviewer.
    # Do not resolve duplicate IDs with different texts by last-writer-wins.
    by_id: dict[str, str] = {}
    for item in selected:
        if item.item_id in by_id and by_id[item.item_id] != item.text:
            return [], ["rule_conflict"]
        by_id[item.item_id] = item.text
    return selected, diagnostics
