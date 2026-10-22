# ruff: noqa: RUF001  -- Chinese chat previews carry full-width punctuation by design.
from datetime import UTC, datetime

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
