from datetime import UTC, datetime
from pathlib import Path

from jobagent.evals.versioning import harness_version, steering_files
from jobagent.skill_resources import default_skill_root

AT = datetime(2026, 10, 20, 2, 0, tzinfo=UTC)


def test_the_same_files_give_the_same_version_whatever_their_order() -> None:
    one = harness_version({"a.md": b"alpha", "b.yaml": b"beta"}, recorded_at=AT)
    two = harness_version({"b.yaml": b"beta", "a.md": b"alpha"}, recorded_at=AT)

    assert one.version_id == two.version_id and one.digest == two.digest
    assert one.version_id.startswith("HVER_")
    assert [f.path for f in one.files] == ["a.md", "b.yaml"]


def test_any_change_to_any_file_is_a_new_version() -> None:
    base = harness_version({"a.md": b"alpha", "b.yaml": b"beta"}, recorded_at=AT)

    assert harness_version({"a.md": b"alpha!", "b.yaml": b"beta"}, recorded_at=AT).digest != (
        base.digest
    )
    assert harness_version({"a.md": b"alpha"}, recorded_at=AT).digest != base.digest


def test_the_steering_files_are_the_drafting_rules_and_the_board_manifests() -> None:
    root = default_skill_root()
    names = [path.relative_to(root).as_posix() for path in steering_files(root)]

    assert {
        "references/message-generation.md",
        "references/conversation.md",
        "references/patrol.md",
        "sources/boss.yaml",
        "sources/liepin.yaml",
        "sources/zhaopin.yaml",
    } <= set(names)
    assert names == sorted(names)


def test_steering_files_skip_ones_a_skill_tree_does_not_have(tmp_path: Path) -> None:
    (tmp_path / "references").mkdir()
    (tmp_path / "references" / "patrol.md").write_text("x", encoding="utf-8")

    assert steering_files(tmp_path) == [tmp_path / "references" / "patrol.md"]
