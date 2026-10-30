"""Compare a board's message list with the last one kept."""

from jobagent.schemas.patrol import PatrolSnapshot, SnapshotChange, SnapshotDiff


def diff_snapshots(previous: PatrolSnapshot | None, current: PatrolSnapshot) -> SnapshotDiff:
    """What appeared, what changed and what is gone since the previous snapshot."""
    if not current.baseline_eligible:
        return SnapshotDiff(
            platform=current.platform, snapshot_id=current.snapshot_id,
            previous_snapshot_id=previous.snapshot_id if previous else None,
            comparison_status="partial" if current.rows_observable else "unavailable",
        )
    if previous is not None and (
        previous.platform != current.platform or not previous.baseline_eligible
    ):
        previous = None
    before = {item.key: item for item in previous.items} if previous else {}
    now = {item.key: item for item in current.items}
    new = [item for key, item in now.items() if key not in before]
    changed = [
        SnapshotChange(before=before[key], after=item)
        for key, item in now.items()
        if key in before
        and (item.preview, item.time_label, item.unread)
        != (before[key].preview, before[key].time_label, before[key].unread)
    ]
    theirs = [
        item for item in new if item.last_from == "them"
        and previous is not None and previous.full_coverage_confirmed
    ] + [
        change.after for change in changed if change.after.last_from == "them"
        and change.after.preview != change.before.preview
    ]
    return SnapshotDiff(
        platform=current.platform,
        snapshot_id=current.snapshot_id,
        previous_snapshot_id=previous.snapshot_id if previous else None,
        new=new,
        changed=changed,
        gone=[key for key in before if key not in now]
        if previous is not None and previous.full_coverage_confirmed
        and current.full_coverage_confirmed else [],
        their_new_messages=theirs,
        comparison_status="compared" if previous is not None else "initialized",
    )
