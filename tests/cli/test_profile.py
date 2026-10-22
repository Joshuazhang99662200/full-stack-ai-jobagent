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


def _candidate_with_confirmed_evidence(db: tuple[str, str]) -> str:
    from jobagent.schemas.candidate import (
        CandidateProfile,
        Confidence,
        EvidenceItem,
        EvidenceType,
    )
    from jobagent.schemas.common import SourceReference, SourceType
    from jobagent.storage.candidate_repository import SqliteCandidateRepository
    from jobagent.storage.database import Database

    database = Database(db[1])
    database.migrate()
    store = SqliteCandidateRepository(database)
    store.save_profile(CandidateProfile(id="CAND_001"))
    store.upsert_evidence(
        "CAND_001",
        EvidenceItem(
            id="EVID_001",
            type=EvidenceType.PROJECT,
            statement="主导金融 Agent 产品",
            source=SourceReference(type=SourceType.RESUME, reference="RESUME_001:page:1"),
            confidence=Confidence.EXPLICIT,
            user_confirmed=True,
        ),
    )
    return "CAND_001"


def test_an_approved_profile_change_is_recorded_once_its_read_back_matches(
    tmp_path: Path,
) -> None:
    db = ("--database", str(tmp_path / "jobagent.sqlite3"))
    candidate = _candidate_with_confirmed_evidence(db)
    before = write(tmp_path, "before.json", [{"name": "advantage", "text": "主导 Agent 产品"}])
    _, base = invoke("profile", "snapshot", str(before), "--platform", "boss",
                     "--now", "2026-10-21T20:00:00+08:00", *db)
    assert isinstance(base, dict)
    proposal_file = write(tmp_path, "proposal.json", {
        "targets": [{
            "platform": "boss",
            "base_version_id": base["version"]["version_id"],
            "changes": [{"name": "advantage", "text": "主导金融 Agent 产品"}],
        }],
        "rationale": "两阶段对比",
        "evidence_ids": ["EVID_001"],
        "decision_rule": "B 期 M2 显著更低则保留",
    })

    code, proposal = invoke("profile", "propose", str(proposal_file), "--candidate", candidate, *db)
    assert code == 0 and isinstance(proposal, dict), proposal
    pid = proposal["proposal_id"]

    code, refused = invoke("profile", "gate", pid, "--platform", "boss", *db)
    assert isinstance(refused, dict) and refused["reason"] == "not_approved"
    code, ask = invoke("profile", "ask", pid, *db)
    assert code == 0 and isinstance(ask, dict) and "主导金融 Agent 产品" in ask["question"]
    code, approval = invoke("profile", "approve", pid, "--request", ask["ask_id"],
                            "--answer", "同意", *db)
    assert code == 0 and isinstance(approval, dict), approval

    code, gate = invoke("profile", "gate", pid, "--platform", "boss", *db)
    assert isinstance(gate, dict) and gate["allowed"], gate

    after = write(tmp_path, "after.json", [{"name": "advantage", "text": "主导金融 Agent 产品"}])
    code, recorded = invoke("profile", "record", pid, "--platform", "boss", "--result", "applied",
                            "--readback", str(after), "--now", "2026-10-21T20:30:00+08:00", *db)
    assert code == 0 and isinstance(recorded, dict), recorded
    assert recorded["application"]["result"] == "applied"
    assert recorded["version"]["origin"] == "agent"
    assert "主导" not in json.dumps(recorded, ensure_ascii=False)

    _, versions = invoke("profile", "versions", "--platform", "boss", *db)
    assert isinstance(versions, list) and [v["origin"] for v in versions] == ["baseline", "agent"]
    code, again = invoke("profile", "gate", pid, "--platform", "boss", *db)
    assert isinstance(again, dict) and again["reason"] == "already_recorded"
