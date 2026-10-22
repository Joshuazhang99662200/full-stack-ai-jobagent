# ruff: noqa: RUF001  -- Chinese greetings carry full-width punctuation by design.
import json
from pathlib import Path

from typer.testing import CliRunner

from jobagent.cli.app import app

runner = CliRunner()
GREETING = "您好，我现任 AI 产品负责人，主导初创公司多款 Agent 产品从 0 到 1 开发。方便聊聊吗？"
JD = "岗位职责：负责 Agent 产品的规划与落地，熟悉 Skill 与工作流设计，能独立做出可运行的原型。"


def invoke(*args: str) -> tuple[int, object]:
    result = runner.invoke(app, list(args))
    try:
        return result.exit_code, json.loads(result.stdout)
    except ValueError:
        return result.exit_code, result.stdout


def stored_jobs(tmp_path: Path) -> tuple[Path, list[str]]:
    database = tmp_path / "jobagent.sqlite3"
    ids = []
    for name in ("alpha", "beta"):
        jd = tmp_path / f"{name}.txt"
        jd.write_text(JD + name, encoding="utf-8")
        _, job = invoke(
            "jobs",
            "add-jd",
            str(jd),
            "--title",
            "Agent 产品经理",
            "--company",
            name,
            "--url",
            f"https://www.zhipin.com/job_detail/{name}.html",
            "--source",
            "boss",
            "--database",
            str(database),
        )
        assert isinstance(job, dict)
        ids.append(job["id"])
    return database, ids


def drafted(tmp_path: Path) -> tuple[Path, str]:
    database, ids = stored_jobs(tmp_path)
    drafts = tmp_path / "drafts.json"
    drafts.write_text(
        json.dumps([{"job_id": i, "platform": "boss", "text": GREETING} for i in ids]),
        encoding="utf-8",
    )
    code, report = invoke("outreach", "draft-batch", str(drafts), "--database", str(database))
    assert code == 0, report
    assert isinstance(report, dict) and report["rejected"] == []
    return database, report["batch"]["batch_id"]


def test_batch_flow_from_question_to_one_recorded_send(tmp_path: Path) -> None:
    database, batch_id = drafted(tmp_path)
    db = ("--database", str(database))

    code, ask = invoke("outreach", "ask", batch_id, *db)
    assert code == 0 and isinstance(ask, dict)
    assert GREETING in ask["question"]

    code, approval = invoke(
        "outreach",
        "approve",
        batch_id,
        "--request",
        ask["ask_id"],
        "--items",
        "1-2",
        "--answer",
        "发 1-2",
        *db,
    )
    assert code == 0, approval
    assert isinstance(approval, dict) and approval["approved_numbers"] == [1, 2]

    code, lease = invoke("outreach", "lease", "boss", "--session", "S1", *db)
    assert code == 0, lease
    code, decision = invoke(
        "outreach", "next", batch_id, "--platform", "boss", "--session", "S1", *db
    )
    assert code == 0 and isinstance(decision, dict) and decision["allowed"]
    assert decision["item"]["number"] == 1

    code, audit = invoke(
        "outreach", "record", batch_id, "1", "--result", "sent", "--session", "S1", *db
    )
    assert code == 0, audit
    code, wait = invoke("outreach", "next", batch_id, "--platform", "boss", "--session", "S1", *db)
    assert isinstance(wait, dict) and wait["reason"] == "too_soon"

    code, status = invoke("outreach", "status", batch_id, *db)
    assert isinstance(status, dict)
    assert [row["result"] for row in status["items"]] == ["sent", None]


def test_record_requires_the_lease_and_approval_requires_a_question(tmp_path: Path) -> None:
    database, batch_id = drafted(tmp_path)
    db = ("--database", str(database))

    code, refused = invoke(
        "outreach",
        "approve",
        batch_id,
        "--request",
        "OASK_NEVER",
        "--items",
        "1",
        "--answer",
        "发 1",
        *db,
    )
    assert code == 1 and isinstance(refused, dict)
    assert refused["error"]["code"] == "APPROVAL_REQUIRED"

    _, ask = invoke("outreach", "ask", batch_id, *db)
    assert isinstance(ask, dict)
    invoke(
        "outreach",
        "approve",
        batch_id,
        "--request",
        ask["ask_id"],
        "--items",
        "1",
        "--answer",
        "发 1",
        *db,
    )
    code, no_lease = invoke(
        "outreach", "record", batch_id, "1", "--result", "sent", "--session", "S9", *db
    )
    assert code == 1 and isinstance(no_lease, dict)
    assert no_lease["error"]["details"]["reason"] == "lease_not_held"


def test_draft_batch_reads_stored_match_tiers_and_skips_weak_matches(tmp_path: Path) -> None:
    from jobagent.schemas.candidate import CandidateProfile
    from jobagent.schemas.jobs import MatchDecision, MatchResult
    from jobagent.storage.candidate_repository import SqliteCandidateRepository
    from jobagent.storage.database import Database
    from jobagent.storage.job_repository import SqliteJobRepository

    database, ids = stored_jobs(tmp_path)
    SqliteCandidateRepository(Database(database)).save_profile(
        CandidateProfile(id="CAND_001", headline="AI 产品负责人")
    )
    jobs = SqliteJobRepository(Database(database))
    decisions = (MatchDecision.WEAK_MATCH, MatchDecision.STRONG_MATCH)
    for job_id, decision in zip(ids, decisions, strict=True):
        jobs.save_match(
            "CAND_001",
            job_id,
            evidence_digest="sha256:" + "0" * 64,
            requirements_digest="sha256:" + "1" * 64,
            policy_digest="sha256:" + "2" * 64,
            result=MatchResult(overall=0.5, decision=decision, strengths=["Agent"]),
        )
    drafts = tmp_path / "drafts.json"
    drafts.write_text(
        json.dumps([{"job_id": i, "platform": "boss", "text": GREETING} for i in ids]),
        encoding="utf-8",
    )

    code, report = invoke(
        "outreach", "draft-batch", str(drafts), "--candidate", "CAND_001",
        "--database", str(database),
    )

    assert code == 0 and isinstance(report, dict)
    assert [i["job_id"] for i in report["batch"]["items"]] == [ids[1]]
    assert report["batch"]["items"][0]["match_tier"] == "strong_match"
    assert report["rejected"][0]["reasons"] == ["weak_match"]


def test_jobs_the_person_picked_skip_the_match_tier_rule(tmp_path: Path) -> None:
    from jobagent.schemas.candidate import CandidateProfile
    from jobagent.schemas.jobs import MatchDecision, MatchResult
    from jobagent.storage.candidate_repository import SqliteCandidateRepository
    from jobagent.storage.database import Database
    from jobagent.storage.job_repository import SqliteJobRepository

    database, ids = stored_jobs(tmp_path)
    SqliteCandidateRepository(Database(database)).save_profile(
        CandidateProfile(id="CAND_001", headline="AI 产品负责人")
    )
    SqliteJobRepository(Database(database)).save_match(
        "CAND_001",
        ids[0],
        evidence_digest="sha256:" + "0" * 64,
        requirements_digest="sha256:" + "1" * 64,
        policy_digest="sha256:" + "2" * 64,
        result=MatchResult(overall=0.4, decision=MatchDecision.WEAK_MATCH, strengths=["Agent"]),
    )
    drafts = tmp_path / "drafts.json"
    drafts.write_text(
        json.dumps([{"job_id": ids[0], "platform": "boss", "text": GREETING}]), encoding="utf-8"
    )

    code, report = invoke(
        "outreach", "draft-batch", str(drafts), "--candidate", "CAND_001", "--hand-picked",
        "--database", str(database),
    )

    assert code == 0 and isinstance(report, dict) and report["rejected"] == []
    assert report["batch"]["items"][0]["match_tier"] == "hand_picked"


def test_a_withdrawn_question_can_no_longer_be_approved(tmp_path: Path) -> None:
    database, batch_id = drafted(tmp_path)
    db = ("--database", str(database))
    _, ask = invoke("outreach", "ask", batch_id, *db)
    assert isinstance(ask, dict)

    code, withdrawn = invoke(
        "outreach", "withdraw", batch_id, "--reason", "旧口吻招呼，按现行规则作废", *db
    )
    assert code == 0 and isinstance(withdrawn, dict) and withdrawn["batch_id"] == batch_id

    code, refused = invoke(
        "outreach", "approve", batch_id, "--request", ask["ask_id"], "--items", "1",
        "--answer", "发 1", *db,
    )
    assert code == 1 and isinstance(refused, dict)
    assert "withdrawn" in refused["error"]["message"].lower()


def test_a_drafted_batch_carries_its_strategy_tags_and_harness_version(tmp_path: Path) -> None:
    from jobagent.storage.database import Database
    from jobagent.storage.evals_repository import SqliteEvalsRepository

    database, ids = stored_jobs(tmp_path)
    drafts = tmp_path / "drafts.json"
    drafts.write_text(
        json.dumps(
            [{"job_id": ids[0], "platform": "boss", "text": GREETING, "variant": "opening_a"}]
        ),
        encoding="utf-8",
    )
    code, report = invoke("outreach", "draft-batch", str(drafts), "--database", str(database))
    assert code == 0 and isinstance(report, dict), report

    batch = report["batch"]
    assert batch["items"][0]["variant"] == "opening_a"
    version = SqliteEvalsRepository(Database(database)).get_harness_version(
        batch["harness_version"]
    )
    assert version is not None
    assert "references/message-generation.md" in [f.path for f in version.files]
