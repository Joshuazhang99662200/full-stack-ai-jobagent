# ruff: noqa: RUF001  -- Chinese job text carries full-width punctuation by design.
import json
from pathlib import Path

from jobagent.schemas.candidate import (
    CandidateProfile,
    Confidence,
    EvidenceItem,
    EvidenceType,
)
from jobagent.schemas.common import SourceReference, SourceType
from jobagent.schemas.job_intelligence import (
    CandidateFilterContext,
    RequirementEvidenceMatch,
    RequirementMatchOutcome,
    RequirementMatchSet,
)
from jobagent.schemas.jobs import JobRequirement, JobRequirementProfile, RequirementPriority
from jobagent.storage.candidate_repository import SqliteCandidateRepository
from jobagent.storage.database import Database
from tests.cli.test_outreach import invoke

JD = "岗位职责：负责 Agent 产品规划，熟悉 Skill 与工作流设计，能独立做出可运行的原型。"


def setup(tmp_path: Path) -> tuple[Path, dict[str, str], Path, Path]:
    database = tmp_path / "jobagent.sqlite3"
    db = Database(database)
    db.migrate()
    candidates = SqliteCandidateRepository(db)
    candidates.save_profile(CandidateProfile(id="CAND_001", headline="AI 产品负责人"))
    candidates.upsert_evidence(
        "CAND_001",
        EvidenceItem(
            id="EVID_SKILL",
            type=EvidenceType.EXPERIENCE,
            statement="把提示词沉淀为模块化 Skill,按场景组装为 Agent 工作流。",
            source=SourceReference(type=SourceType.RESUME, reference="RESUME_001#p1"),
            confidence=Confidence.EXPLICIT,
            user_confirmed=True,
        ),
    )
    jobs: dict[str, str] = {}
    postings = (("ready", "Agent 产品经理"), ("pending", "AI 产品经理"), ("sales", "AI 销售经理"))
    for name, title in postings:
        path = tmp_path / f"{name}.txt"
        path.write_text(JD + name, encoding="utf-8")
        _, job = invoke(
            "jobs", "add-jd", str(path), "--title", title, "--company", name,
            "--url", f"https://example.com/{name}", "--location", "上海",
            "--database", str(database),
        )
        assert isinstance(job, dict)
        jobs[name] = job["id"]

    context = tmp_path / "filter_context.json"
    context.write_text(
        CandidateFilterContext(
            candidate_id="CAND_001", allowed_locations=["上海"], excluded_role_terms=["销售"]
        ).model_dump_json(),
        encoding="utf-8",
    )
    reviewed = tmp_path / "reviewed"
    reviewed.mkdir()
    ready = jobs["ready"]
    (reviewed / f"{ready}.requirements.json").write_text(
        JobRequirementProfile(
            job_id=ready,
            requirements=[
                JobRequirement(
                    id="REQ_SKILL",
                    statement="熟悉 Skill 与工作流设计",
                    category="agent_design",
                    priority=RequirementPriority.MUST,
                    source_span="熟悉 Skill 与工作流设计",
                )
            ],
        ).model_dump_json(),
        encoding="utf-8",
    )
    (reviewed / f"{ready}.matches.json").write_text(
        RequirementMatchSet(
            job_id=ready,
            candidate_id="CAND_001",
            matches=[
                RequirementEvidenceMatch(
                    requirement_id="REQ_SKILL",
                    outcome=RequirementMatchOutcome.SUPPORTED,
                    evidence_ids=["EVID_SKILL"],
                    explanation="证据写明搭建 Skill 与 Agent 工作流。",
                )
            ],
        ).model_dump_json(),
        encoding="utf-8",
    )
    return database, jobs, context, reviewed


def test_triage_filters_ranks_ready_jobs_and_lists_the_rest(tmp_path: Path) -> None:
    database, jobs, context, reviewed = setup(tmp_path)

    code, report = invoke(
        "jobs", "triage", "CAND_001", str(context), str(reviewed), "--all-stored",
        "--database", str(database),
    )

    assert code == 0, report
    assert isinstance(report, dict)
    assert [item["job_id"] for item in report["rejected"]] == [jobs["sales"]]
    assert "ROLE_EXCLUSION" in json.dumps(report["rejected"])
    assert [item["job_id"] for item in report["ranked"]] == [jobs["ready"]]
    assert [item["job_id"] for item in report["pending"]] == [jobs["pending"]]
    assert report["pending"][0]["missing"] == ["requirements", "matches"]

    worklist = json.loads((reviewed / "worklist.json").read_text(encoding="utf-8"))
    assert [item["job_id"] for item in worklist["jobs"]] == [jobs["pending"]]
    assert worklist["jobs"][0]["jd_raw"].startswith("岗位职责")
    assert worklist["jobs"][0]["write"] == [
        f"{jobs['pending']}.requirements.json",
        f"{jobs['pending']}.matches.json",
    ]
    assert [item["id"] for item in worklist["confirmed_evidence"]] == ["EVID_SKILL"]


def test_triage_can_take_explicit_job_ids(tmp_path: Path) -> None:
    database, jobs, context, reviewed = setup(tmp_path)

    code, report = invoke(
        "jobs", "triage", "CAND_001", str(context), str(reviewed),
        "--job", jobs["ready"], "--database", str(database),
    )

    assert code == 0, report
    assert isinstance(report, dict)
    assert [item["job_id"] for item in report["ranked"]] == [jobs["ready"]]
    assert report["pending"] == [] and report["rejected"] == []


def test_worklist_states_the_rules_triage_will_enforce(tmp_path: Path) -> None:
    database, _, context, reviewed = setup(tmp_path)

    invoke(
        "jobs", "triage", "CAND_001", str(context), str(reviewed), "--all-stored",
        "--database", str(database),
    )

    worklist = json.loads((reviewed / "worklist.json").read_text(encoding="utf-8"))
    rules = " ".join(worklist["rules"])
    for phrase in ("source_span", "risk_signals", "keywords", "missing"):
        assert phrase in rules
    assert worklist["confirmed_evidence"][0]["skills"] == []
    assert "domains" in worklist["confirmed_evidence"][0]


def test_one_invalid_reviewed_job_does_not_stop_the_batch(tmp_path: Path) -> None:
    database, jobs, context, reviewed = setup(tmp_path)
    pending = jobs["pending"]
    (reviewed / f"{pending}.requirements.json").write_text(
        (reviewed / f"{jobs['ready']}.requirements.json")
        .read_text(encoding="utf-8")
        .replace(jobs["ready"], pending),
        encoding="utf-8",
    )
    (reviewed / f"{pending}.matches.json").write_text(
        RequirementMatchSet(
            job_id=pending,
            candidate_id="CAND_001",
            matches=[
                RequirementEvidenceMatch(
                    requirement_id="REQ_SKILL",
                    outcome=RequirementMatchOutcome.PARTIAL,
                    evidence_ids=[],
                    explanation="没有引用证据。",
                )
            ],
        ).model_dump_json(),
        encoding="utf-8",
    )

    code, report = invoke(
        "jobs", "triage", "CAND_001", str(context), str(reviewed), "--all-stored",
        "--database", str(database),
    )

    assert code == 0, report
    assert isinstance(report, dict)
    assert [item["job_id"] for item in report["ranked"]] == [jobs["ready"]]
    assert [item["job_id"] for item in report["invalid"]] == [pending]
    assert report["invalid"][0]["reason"] == "inadmissible support"
    assert report["invalid"][0]["requirement_id"] == "REQ_SKILL"
    worklist = json.loads((reviewed / "worklist.json").read_text(encoding="utf-8"))
    assert worklist["jobs"][0]["job_id"] == pending
    assert worklist["jobs"][0]["fix"]["reason"] == "inadmissible support"
