import json
import unicodedata
from pathlib import Path

from typer.testing import CliRunner

from jobagent.cli.app import app
from jobagent.connectors.mock import MockJobSource
from jobagent.jobs.deduplication import JobDeduplicator
from jobagent.jobs.normalization import JobNormalizer
from jobagent.schemas.candidate import (
    CandidateProfile,
    Confidence,
    EvidenceItem,
    EvidenceType,
    Skill,
)
from jobagent.schemas.common import SourceReference, SourceType
from jobagent.schemas.job_intelligence import (
    CandidateFilterContext,
    DeduplicationPolicy,
    JobSearchQuery,
    RequirementEvidenceMatch,
    RequirementMatchOutcome,
    RequirementMatchSet,
)
from jobagent.schemas.jobs import JobRequirement, JobRequirementProfile, RequirementPriority
from jobagent.storage.candidate_repository import SqliteCandidateRepository
from jobagent.storage.database import Database
from jobagent.storage.job_repository import SqliteJobRepository

runner = CliRunner()
FIXTURE = Path("src/jobagent/connectors/fixtures/jobs.json").resolve()


def invoke(*args: str) -> tuple[int, object]:
    result = runner.invoke(app, list(args))
    payload = json.loads(result.stdout) if result.stdout else None
    return result.exit_code, payload


def reviewed_files(tmp_path: Path) -> tuple[Path, Path, str]:
    job = JobNormalizer().normalize(MockJobSource.from_path(FIXTURE).fetch_job("alpha-001"))
    requirements = JobRequirementProfile(
        job_id=job.id,
        requirements=[
            JobRequirement(
                id="REQ_PYTHON",
                statement="Build Python API services",
                category="skill",
                priority=RequirementPriority.MUST,
                source_span="Build Python API services",
                keywords=["Python"],
            )
        ],
        must_have=["Build Python API services"],
        skills=["Python"],
    )
    mappings = RequirementMatchSet(
        job_id=job.id,
        candidate_id="CAND_001",
        matches=[
            RequirementEvidenceMatch(
                requirement_id="REQ_PYTHON",
                outcome=RequirementMatchOutcome.SUPPORTED,
                evidence_ids=["EVID_PYTHON"],
                explanation="Confirmed Python evidence.",
            )
        ],
    )
    requirements_path = tmp_path / "requirements.json"
    mappings_path = tmp_path / "mappings.json"
    requirements_path.write_text(requirements.model_dump_json(), encoding="utf-8")
    mappings_path.write_text(mappings.model_dump_json(), encoding="utf-8")
    return requirements_path, mappings_path, job.id


def seed_candidate(database_path: Path) -> None:
    database = Database(database_path)
    database.migrate()
    repository = SqliteCandidateRepository(database)
    repository.save_profile(CandidateProfile(id="CAND_001"))
    repository.upsert_evidence(
        "CAND_001",
        EvidenceItem(
            id="EVID_PYTHON",
            type=EvidenceType.SKILL,
            statement="Built Python services for production.",
            skills=["Python"],
            source=SourceReference(type=SourceType.RESUME, reference="RESUME_001:page:1"),
            confidence=Confidence.EXPLICIT,
            user_confirmed=True,
        ),
    )


def test_jobs_help_exposes_read_only_intelligence_commands() -> None:
    result = runner.invoke(app, ["jobs", "--help"])

    assert result.exit_code == 0
    for command in (
        "search",
        "fetch",
        "normalize",
        "dedupe",
        "requirements",
        "filter",
        "match",
        "rank",
        "pipeline",
    ):
        assert command in result.stdout
    for forbidden in ("apply", "approve", "preview", "send", "browser"):
        assert forbidden not in result.stdout.casefold()


def test_search_normalize_and_dedupe_emit_contract_json() -> None:
    search_code, search_result = invoke("jobs", "search", "python", "--fixture", str(FIXTURE))
    normalize_code, normalized = invoke("jobs", "normalize", "alpha-001", "--fixture", str(FIXTURE))
    dedupe_code, deduplicated = invoke(
        "jobs",
        "dedupe",
        "alpha-001",
        "beta-991",
        "--near-threshold",
        "0.7",
        "--fixture",
        str(FIXTURE),
    )

    assert search_code == normalize_code == dedupe_code == 0
    assert isinstance(search_result, list) and len(search_result) == 3
    assert isinstance(normalized, dict) and normalized["id"].startswith("JOB_")
    assert isinstance(deduplicated, dict)
    assert len(deduplicated["jobs"]) == 1
    assert len(deduplicated["jobs"][0]["provenance"]) == 2


def test_reviewed_requirements_filter_and_match_are_revalidated(tmp_path: Path) -> None:
    requirements_path, mappings_path, job_id = reviewed_files(tmp_path)
    context_path = tmp_path / "context.json"
    context_path.write_text(
        CandidateFilterContext(candidate_id="CAND_001").model_dump_json(), encoding="utf-8"
    )
    database_path = tmp_path / "jobagent.sqlite3"
    seed_candidate(database_path)

    requirements_code, requirements = invoke(
        "jobs",
        "requirements",
        "alpha-001",
        str(requirements_path),
        "--fixture",
        str(FIXTURE),
    )
    filter_code, filter_result = invoke(
        "jobs",
        "filter",
        "alpha-001",
        str(requirements_path),
        str(context_path),
        "--fixture",
        str(FIXTURE),
    )
    match_code, match_result = invoke(
        "jobs",
        "match",
        "alpha-001",
        str(requirements_path),
        str(mappings_path),
        "CAND_001",
        "--database",
        str(database_path),
        "--fixture",
        str(FIXTURE),
    )

    assert requirements_code == filter_code == match_code == 0
    assert isinstance(requirements, dict) and requirements["job_id"] == job_id
    assert isinstance(filter_result, dict) and filter_result["decision"] == "pass"
    assert isinstance(match_result, dict) and match_result["decision"] == "strong_match"
    assert "Built Python services for production." not in json.dumps(match_result)


def test_fetch_unknown_job_returns_structured_error_without_fixture_body() -> None:
    exit_code, payload = invoke("jobs", "fetch", "missing", "--fixture", str(FIXTURE))

    assert exit_code == 1
    assert isinstance(payload, dict)
    assert payload["error"]["code"] == "JOB_NOT_FOUND"
    assert "Build Python API services" not in json.dumps(payload)


def test_pipeline_consumes_job_keyed_reviewed_files(tmp_path: Path) -> None:
    database_path = tmp_path / "jobagent.sqlite3"
    seed_candidate(database_path)
    reviewed_directory = tmp_path / "reviewed"
    reviewed_directory.mkdir()
    source = MockJobSource.from_path(FIXTURE)
    normalized = [JobNormalizer().normalize(record) for record in source.search(JobSearchQuery())]
    jobs = JobDeduplicator().deduplicate(normalized, DeduplicationPolicy()).jobs
    for job in jobs:
        if "Sales" in job.title:
            statement, keyword = "Lead enterprise sales", "sales"
        elif "Machine Learning" in job.title:
            statement, keyword = "Develop machine learning pipelines", "machine learning"
        else:
            statement, keyword = "Build Python API services", "Python"
        profile = JobRequirementProfile(
            job_id=job.id,
            requirements=[
                JobRequirement(
                    id="REQ_PRIMARY",
                    statement=statement,
                    category="skill",
                    priority=RequirementPriority.MUST,
                    source_span=statement,
                    keywords=[keyword],
                )
            ],
            must_have=[statement],
            skills=[keyword],
        )
        (reviewed_directory / f"{job.id}.requirements.json").write_text(
            profile.model_dump_json(), encoding="utf-8"
        )
        if "Sales" not in job.title:
            supported = "Python Platform" in job.title
            mappings = RequirementMatchSet(
                job_id=job.id,
                candidate_id="CAND_001",
                matches=[
                    RequirementEvidenceMatch(
                        requirement_id="REQ_PRIMARY",
                        outcome=(
                            RequirementMatchOutcome.SUPPORTED
                            if supported
                            else RequirementMatchOutcome.UNCERTAIN
                        ),
                        evidence_ids=["EVID_PYTHON"] if supported else [],
                        explanation="Reviewed requirement mapping.",
                    )
                ],
            )
            (reviewed_directory / f"{job.id}.matches.json").write_text(
                mappings.model_dump_json(), encoding="utf-8"
            )
    context_path = tmp_path / "context.json"
    context_path.write_text(
        CandidateFilterContext(
            candidate_id="CAND_001", excluded_role_terms=["sales"]
        ).model_dump_json(),
        encoding="utf-8",
    )

    exit_code, payload = invoke(
        "jobs",
        "pipeline",
        "CAND_001",
        str(context_path),
        str(reviewed_directory),
        "--database",
        str(database_path),
        "--fixture",
        str(FIXTURE),
    )

    assert exit_code == 0
    assert isinstance(payload, dict)
    assert len(payload["normalized_jobs"]) == 3
    assert len(payload["ranked_jobs"]) == 2
    assert all(item["application_ready"] is False for item in payload["ranked_jobs"])


def test_suggest_queries_reads_the_confirmed_candidate_knowledge_base(tmp_path: Path) -> None:
    database = tmp_path / "jobagent.sqlite3"
    db = Database(database)
    db.migrate()
    repository = SqliteCandidateRepository(db)
    repository.save_profile(
        CandidateProfile(
            id="CAND_001",
            headline="AI Agent Product Lead · CFA",
            skills=[Skill(name="Multi-agent orchestration", evidence_ids=["EVID_A"])],
        )
    )
    repository.upsert_evidence(
        "CAND_001",
        EvidenceItem(
            id="EVID_A",
            type=EvidenceType.SKILL,
            statement="Designed a multi-agent orchestration layer.",
            source=SourceReference(type=SourceType.RESUME, reference="RESUME_001#p1"),
            confidence=Confidence.EXPLICIT,
            user_confirmed=True,
        ),
    )

    code, payload = invoke(
        "jobs", "suggest-queries", "CAND_001", "--database", str(database), "--location", "Shanghai"
    )

    assert code == 0
    assert isinstance(payload, dict)
    terms = [item["term"] for item in payload["suggestions"]]
    assert terms == ["AI Agent Product Lead", "Multi-agent orchestration"]
    assert payload["suggestions"][1]["supporting_evidence_ids"] == ["EVID_A"]
    assert {item["query"]["location"] for item in payload["suggestions"]} == {"Shanghai"}


def test_suggest_queries_accepts_target_roles(tmp_path: Path) -> None:
    database = tmp_path / "jobagent.sqlite3"
    db = Database(database)
    db.migrate()
    repository = SqliteCandidateRepository(db)
    repository.save_profile(CandidateProfile(id="CAND_001", headline="Product Lead"))
    repository.upsert_evidence(
        "CAND_001",
        EvidenceItem(
            id="EVID_A",
            type=EvidenceType.SKILL,
            statement="Designed a multi-agent orchestration layer for AI Agent products.",
            source=SourceReference(type=SourceType.RESUME, reference="RESUME_001#p1"),
            confidence=Confidence.EXPLICIT,
            user_confirmed=True,
        ),
    )

    code, payload = invoke(
        "jobs",
        "suggest-queries",
        "CAND_001",
        "--database",
        str(database),
        "--target-role",
        "AI Agent 产品经理",
    )

    assert code == 0, payload
    assert isinstance(payload, dict)
    terms = [item["term"] for item in payload["suggestions"]]
    assert terms[:3] == ["AI Agent产品经理", "AI产品经理", "Agent产品经理"]


def test_suggest_queries_reports_a_missing_candidate(tmp_path: Path) -> None:
    database = tmp_path / "jobagent.sqlite3"
    code, payload = invoke("jobs", "suggest-queries", "CAND_404", "--database", str(database))

    assert code == 1
    assert isinstance(payload, dict)
    assert payload["error"]["code"] == "JOB_NOT_FOUND"


def test_unknown_source_connector_is_rejected() -> None:
    code, payload = invoke("jobs", "search", "python", "--source", "bogus")

    assert code == 1
    assert isinstance(payload, dict)
    assert payload["error"]["code"] == "CONTRACT_VALIDATION_ERROR"
    assert "liepin" in payload["error"]["details"]["known"]
    assert "mock" in payload["error"]["details"]["known"]


def test_liepin_cannot_be_used_where_a_full_job_observation_is_required() -> None:
    """Liepin has no JD text, so `jobs search` must redirect instead of faking one."""
    code, payload = invoke("jobs", "search", "python", "--source", "liepin")

    assert code == 1
    assert isinstance(payload, dict)
    assert payload["error"]["code"] == "CONTRACT_VALIDATION_ERROR"
    assert payload["error"]["details"]["use_instead"] == "jobs listings"


def test_normalize_persists_the_job_so_a_real_posting_can_be_referenced_later(
    tmp_path: Path,
) -> None:
    """Boards that publish no JD in search results cannot be re-fetched by source id."""
    database_path = tmp_path / "jobagent.sqlite3"

    normalize_code, normalized = invoke(
        "jobs",
        "normalize",
        "alpha-001",
        "--fixture",
        str(FIXTURE),
        "--database",
        str(database_path),
    )

    assert normalize_code == 0
    assert isinstance(normalized, dict)
    stored = SqliteJobRepository(Database(database_path)).get_job(normalized["id"])
    assert stored is not None
    assert stored.id == normalized["id"]


def test_requirements_accepts_a_stored_job_reference(tmp_path: Path) -> None:
    database_path = tmp_path / "jobagent.sqlite3"
    invoke(
        "jobs", "normalize", "alpha-001",
        "--fixture", str(FIXTURE), "--database", str(database_path),
    )
    requirements_path, _, job_id = reviewed_files(tmp_path)

    code, payload = invoke(
        "jobs",
        "requirements",
        job_id,
        str(requirements_path),
        "--database",
        str(database_path),
    )

    assert code == 0
    assert isinstance(payload, dict)
    assert payload["job_id"] == job_id


def test_stored_job_reference_without_a_database_is_a_structured_error(
    tmp_path: Path,
) -> None:
    requirements_path, _, job_id = reviewed_files(tmp_path)

    code, payload = invoke("jobs", "requirements", job_id, str(requirements_path))

    assert code == 1
    assert isinstance(payload, dict)
    assert payload["error"]["details"]["job_id"] == job_id


def test_source_job_ids_still_resolve_through_the_fixture(tmp_path: Path) -> None:
    requirements_path, _, _ = reviewed_files(tmp_path)

    code, payload = invoke(
        "jobs", "requirements", "alpha-001", str(requirements_path), "--fixture", str(FIXTURE)
    )

    assert code == 0
    assert isinstance(payload, dict)


# Full-width punctuation is deliberate: real JDs carry it and normalization folds it.
MANUAL_JD = (
    "岗位职责：主导 Skill 平台的产品设计与落地，输出 PRD 与原型。"  # noqa: RUF001
    "任职要求：熟悉 Skill、Agent、Workflow 的设计，能用 Claude Code 独立做出可运行的原型。"  # noqa: RUF001
)


def _add_jd(tmp_path: Path, *extra: str) -> tuple[int, object, Path]:
    database_path = tmp_path / "jobagent.sqlite3"
    jd_path = tmp_path / "jd.txt"
    jd_path.write_text(MANUAL_JD, encoding="utf-8")
    code, payload = invoke(
        "jobs",
        "add-jd",
        str(jd_path),
        "--title",
        "Skill 平台产品经理",
        "--company",
        "LoomLoom",
        "--url",
        "https://example.com/jobs/loomloom",
        "--database",
        str(database_path),
        *extra,
    )
    return code, payload, database_path


def test_add_jd_stores_a_user_supplied_posting_as_a_job(tmp_path: Path) -> None:
    code, job, database_path = _add_jd(tmp_path, "--location", "上海")

    assert code == 0
    assert isinstance(job, dict)
    assert job["id"].startswith("JOB_")
    stored = SqliteJobRepository(Database(database_path)).get_job(job["id"])
    assert stored is not None
    assert stored.jd_raw == unicodedata.normalize("NFKC", MANUAL_JD)
    assert stored.provenance[0].source == "manual"


def test_add_jd_job_feeds_requirement_revalidation(tmp_path: Path) -> None:
    _, job, database_path = _add_jd(tmp_path)
    assert isinstance(job, dict)
    requirements_path = tmp_path / "requirements.json"
    profile = JobRequirementProfile(
        job_id=job["id"],
        requirements=[
            JobRequirement(
                id="REQ_SKILL",
                statement="熟悉 Skill、Agent、Workflow 的设计",
                category="agent_design",
                priority=RequirementPriority.MUST,
                source_span="熟悉 Skill、Agent、Workflow 的设计",
            )
        ],
    )
    requirements_path.write_text(profile.model_dump_json(), encoding="utf-8")

    code, payload = invoke(
        "jobs", "requirements", job["id"], str(requirements_path), "--database", str(database_path)
    )

    assert code == 0, payload
    assert isinstance(payload, dict) and payload["job_id"] == job["id"]


def test_add_jd_is_idempotent_for_the_same_posting(tmp_path: Path) -> None:
    _, first, _ = _add_jd(tmp_path)
    _, second, _ = _add_jd(tmp_path)

    assert isinstance(first, dict) and isinstance(second, dict)
    assert first["id"] == second["id"]


def test_add_jd_rejects_a_too_short_description(tmp_path: Path) -> None:
    jd_path = tmp_path / "jd.txt"
    jd_path.write_text("产品经理", encoding="utf-8")

    code, payload = invoke(
        "jobs",
        "add-jd",
        str(jd_path),
        "--title",
        "PM",
        "--company",
        "X",
        "--url",
        "https://example.com/j",
        "--database",
        str(tmp_path / "db.sqlite3"),
    )

    assert code == 1
    assert isinstance(payload, dict) and "too short" in payload["error"]["message"]


def _observation(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "source": "boss",
        "access_state": "authenticated",
        "completeness": "full",
        "source_job_id": "abc123",
        "title": "AI 产品经理（懂 Skill）",  # noqa: RUF001
        "company": "胜算云",
        "location": "上海",
        "salary_text": "20-30K",
        "jd_raw": MANUAL_JD,
        "url": "https://www.zhipin.com/job_detail/abc123.html",
        "collected_at": "2026-10-13T10:00:00Z",
    }
    record.update(overrides)
    return record


def _import(tmp_path: Path, records: list[dict[str, object]]) -> tuple[int, object, Path]:
    database_path = tmp_path / "jobagent.sqlite3"
    import hashlib
    from datetime import UTC, datetime

    from jobagent.schemas.sourcing import ReadOutcome, ReadReservation
    from jobagent.storage.read_repository import SqliteReadRepository

    db = Database(database_path)
    db.migrate()
    reads = SqliteReadRepository(db)
    records = [dict(row) for row in records]
    for row in records:
        if row.get("source") != "boss":
            continue
        identity = hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()
        attempt_id = "TEST_" + identity
        row["read_attempt_id"] = attempt_id
        at = datetime.fromisoformat(str(row["collected_at"]).replace("Z", "+00:00"))
        reads.reserve(ReadReservation(
            attempt_id=attempt_id, source="boss", target_url=str(row["url"]),
            profile="standard", expected_daily_cap=50,
        ), daily_cap=50, now=at.astimezone(UTC))
        reads.record(ReadOutcome(attempt_id=attempt_id, status="read"), now=at)
    path = tmp_path / "observations.json"
    path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    code, payload = invoke(
        "jobs", "import-observations", str(path), "--database", str(database_path)
    )
    return code, payload, database_path


def test_import_observations_stores_host_captured_postings(tmp_path: Path) -> None:
    code, report, database_path = _import(tmp_path, [_observation()])

    assert code == 0, report
    assert isinstance(report, dict)
    assert report["rejected"] == []
    job_id = report["stored"][0]["job_id"]
    stored = SqliteJobRepository(Database(database_path)).get_job(job_id)
    assert stored is not None and stored.source == "boss"


def test_import_observations_rejects_records_that_break_the_board_contract(
    tmp_path: Path,
) -> None:
    records = [
        _observation(url="https://evil.example/job/1"),
        _observation(source="mock", source_job_id="m1"),
        _observation(source_job_id="short", jd_raw="产品经理"),
        _observation(source_job_id="gate", jd_raw="请完成安全验证后继续访问。" * 5),
    ]

    code, report, _ = _import(tmp_path, records)

    assert code == 0
    assert isinstance(report, dict)
    assert report["stored"] == []
    assert [item["reason"] for item in report["rejected"]] == [
        "url_outside_board",
        "no_host_route",
        "jd_too_short",
        "gate_page",
    ]


def test_import_observations_is_idempotent(tmp_path: Path) -> None:
    _, first, _ = _import(tmp_path, [_observation()])
    _, second, _ = _import(tmp_path, [_observation()])

    assert isinstance(first, dict) and isinstance(second, dict)
    assert first["stored"][0]["job_id"] == second["stored"][0]["job_id"]


def test_import_keeps_every_search_that_turned_up_a_posting(tmp_path: Path) -> None:
    """A job found again by another search keeps both; the first search is never lost."""
    _, first, database_path = _import(tmp_path, [_observation(search_term="AI 产品经理")])
    _import(
        tmp_path,
        [_observation(search_term="Agent 产品", collected_at="2026-10-14T10:00:00Z")],
    )
    _import(tmp_path, [_observation(search_term="AI 产品经理")])
    _import(tmp_path, [_observation(source_job_id="nosearch")])

    assert isinstance(first, dict)
    job_id = first["stored"][0]["job_id"]
    hits = SqliteJobRepository(Database(database_path)).search_hits()
    assert [(h.job_id, h.search_term) for h in hits] == [
        (job_id, "AI 产品经理"),
        (job_id, "Agent 产品"),
    ]
    assert hits[0].source == "boss"


def test_import_report_flags_known_and_contacted_postings(tmp_path: Path) -> None:
    _, first, _ = _import(tmp_path, [_observation()])
    assert isinstance(first, dict)
    assert first["stored"][0]["known_before"] is False
    assert first["stored"][0]["contacted"] is False

    _, again, _ = _import(tmp_path, [_observation()])
    assert isinstance(again, dict) and again["stored"][0]["known_before"] is True


def test_sourcing_budget_counts_todays_reads_per_board(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    now = datetime.now(UTC).isoformat()
    _import(
        tmp_path,
        [
            _observation(collected_at=now),
            _observation(
                source_job_id="def456",
                url="https://www.zhipin.com/job_detail/def456.html",
                collected_at=now,
            ),
        ],
    )

    code, budget = invoke(
        "jobs", "sourcing-budget", "--database", str(tmp_path / "jobagent.sqlite3")
    )

    assert code == 0, budget
    assert isinstance(budget, dict)
    boss = budget["boss"]
    assert boss["read_today"] == 2
    assert boss["remaining"] == boss["daily_cap"] - 2
