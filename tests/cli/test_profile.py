import json
from pathlib import Path

from tests.cli.test_outreach import invoke


def write(tmp_path: Path, name: str, payload: object) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_profile_snapshots_open_a_version_only_when_the_profile_changes(tmp_path: Path) -> None:
    db = ("--database", str(tmp_path / "jobagent.sqlite3"))
    first = write(tmp_path, "a.json", [{"name": "advantage", "text": "主导 Agent 产品"}])
    same = write(tmp_path, "b.json", [{"name": "advantage", "text": "主导 Agent 产品"}])
    edited = write(tmp_path, "c.json", [{"name": "advantage", "text": "主导金融 Agent 产品"}])

    code, one = invoke("profile", "snapshot", str(first), "--platform", "boss",
                       "--now", "2026-10-20T09:00:00+08:00", *db)
    assert code == 0 and isinstance(one, dict), one
    assert one["version"]["origin"] == "baseline"
    # The profile text stays in the local database; the report names fields only.
    assert "主导" not in json.dumps(one, ensure_ascii=False)

    code, two = invoke("profile", "snapshot", str(same), "--platform", "boss",
                       "--now", "2026-10-21T09:00:00+08:00", *db)
    assert code == 0 and isinstance(two, dict) and two["version"] is None

    code, three = invoke("profile", "snapshot", str(edited), "--platform", "boss",
                         "--now", "2026-10-22T09:00:00+08:00", *db)
    assert code == 0 and isinstance(three, dict)
    assert three["version"]["origin"] == "external"
    assert three["version"]["changed_fields"] == ["advantage"]

    code, versions = invoke("profile", "versions", "--platform", "boss", *db)
    assert code == 0 and isinstance(versions, list)
    assert [v["origin"] for v in versions] == ["baseline", "external"]

    code, other = invoke("profile", "versions", "--platform", "liepin", *db)
    assert code == 0 and other == []


def test_a_profile_snapshot_must_hold_fields(tmp_path: Path) -> None:
    db = ("--database", str(tmp_path / "jobagent.sqlite3"))
    empty = write(tmp_path, "empty.json", [])

    code, result = invoke("profile", "snapshot", str(empty), "--platform", "boss", *db)
    assert code == 1 and isinstance(result, dict) and "error" in result
