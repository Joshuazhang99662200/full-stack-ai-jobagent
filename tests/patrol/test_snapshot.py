# ruff: noqa: RUF001  -- Chinese chat previews carry full-width punctuation by design.
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from jobagent.patrol.snapshot import diff_snapshots
from jobagent.schemas.patrol import PatrolSnapshot, SnapshotItem

AT = datetime(2026, 10, 19, 2, 0, tzinfo=UTC)


def item(key: str, preview: str, last_from: str = "them", unread: int = 0) -> SnapshotItem:
    return SnapshotItem(
        key=key, recruiter=key, company="某公司", preview=preview, time_label="10:00",
        unread=unread, last_from=last_from,  # type: ignore[arg-type]
    )


def snap(snapshot_id: str, *items: SnapshotItem) -> PatrolSnapshot:
    return PatrolSnapshot(
        snapshot_id=snapshot_id, platform="boss", captured_at=AT, items=list(items)
    )


def test_the_first_snapshot_reports_every_conversation_as_new() -> None:
    result = diff_snapshots(None, snap("PSNAP_A", item("赵先生", "你好")))

    assert [i.key for i in result.new] == ["赵先生"]
    assert result.previous_snapshot_id is None


def test_a_changed_preview_from_the_recruiter_is_a_new_message() -> None:
    before = snap(
        "PSNAP_A", item("赵先生", "您好，我是Alex", last_from="us"), item("钱女士", "你好")
    )
    after = snap(
        "PSNAP_B",
        item("赵先生", "方便发份简历吗", last_from="them", unread=1),
        item("钱女士", "你好"),
        item("郝女士", "您正在与Boss郝女士沟通", last_from="system"),
    )

    result = diff_snapshots(before, after)

    assert [i.key for i in result.new] == ["郝女士"]
    assert [c.after.key for c in result.changed] == ["赵先生"]
    assert [i.key for i in result.their_new_messages] == ["赵先生"]
    assert result.previous_snapshot_id == "PSNAP_A"


def test_our_own_new_message_is_a_change_but_not_their_message() -> None:
    before = snap("PSNAP_A", item("郝女士", "您正在与Boss郝女士沟通", last_from="system"))
    after = snap("PSNAP_B", item("郝女士", "您好，我是Alex", last_from="us"))

    result = diff_snapshots(before, after)

    assert len(result.changed) == 1 and result.their_new_messages == []


def declared(snapshot_id: str, *items: SnapshotItem, **states: str) -> PatrolSnapshot:
    return PatrolSnapshot.model_validate({
        "snapshot_id": snapshot_id, "platform": "boss", "captured_at": AT,
        "items": list(items), "access_state": "authenticated", "coverage": "full",
        "load_state": "loaded", **states,
    })


def test_partial_snapshot_cannot_create_missing_or_new_message_events() -> None:
    before = declared("PSNAP_A", item("A", "Before"), item("B", "Existing"))
    after = declared("PSNAP_B", item("A", "Changed"), item("C", "New"), coverage="partial")

    result = diff_snapshots(before, after)

    assert result.gone == result.new == result.changed == result.their_new_messages == []
    assert result.comparison_status == "partial"


@pytest.mark.parametrize("state", ["login_required", "loading", "verification", "risk_control"])
def test_unavailable_snapshot_cannot_be_a_successful_baseline(state: str) -> None:
    current = declared("PSNAP_B", access_state=state)
    result = diff_snapshots(declared("PSNAP_A", item("A", "Existing")), current)
    assert not current.baseline_eligible
    assert result.comparison_status == "unavailable"
    assert not result.gone and not result.their_new_messages


def test_legacy_history_remains_labeled_without_confirming_zero_or_missing() -> None:
    empty = snap("PSNAP_A")
    assert empty.access_state == empty.coverage == empty.load_state == "legacy_declared"
    assert not empty.baseline_eligible
    result = diff_snapshots(snap("PSNAP_B", item("A", "Existing")), empty)
    assert not result.gone


def test_unread_badge_only_change_does_not_prove_a_new_reply() -> None:
    before = declared("PSNAP_A", item("A", "Same preview", unread=1))
    after = declared("PSNAP_B", item("A", "Same preview", unread=2))
    result = diff_snapshots(before, after)
    assert result.changed
    assert not result.their_new_messages


def test_duplicate_conversation_keys_cannot_silently_replace_one_another() -> None:
    with pytest.raises(ValidationError, match="unique"):
        declared("PSNAP_A", item("A", "First"), item("A", "Second"))


def test_legacy_duplicate_keys_remain_readable_but_cannot_be_a_baseline() -> None:
    old = snap("PSNAP_A", item("A", "First"), item("A", "Second"))
    assert len(old.items) == 2 and old.legacy_declared
    assert not old.baseline_eligible and not old.rows_observable
