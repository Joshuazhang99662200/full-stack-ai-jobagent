"""Take explicit front rows and deduplicate only exact same-source platform IDs."""

from collections.abc import Sequence

from jobagent.errors import ContractValidationError
from jobagent.schemas.job_intelligence import JobListing
from jobagent.schemas.sourcing import QuerySelection


def select_query_results(
    items: Sequence[JobListing],
    *,
    requested: int,
    source: str,
    seen: set[str],
) -> QuerySelection:
    if type(requested) is not int or requested < 1:
        raise ContractValidationError("Requested result count must be a positive integer.")
    if any(item.source != source for item in items):
        raise ContractValidationError("Query results belong to another source.")
    taken = items[:requested]
    known = set(seen)
    selected, duplicates = [], []
    for item in taken:
        if item.source_job_id in known:
            duplicates.append(item.source_job_id)
        else:
            selected.append(item)
            known.add(item.source_job_id)
    return QuerySelection(
        requested=requested,
        observed_count=len(items),
        taken_count=len(taken),
        shortfall=max(0, requested - len(taken)),
        items=selected,
        duplicate_ids=duplicates,
    )
