import json
from pathlib import Path

from typer.testing import CliRunner

from jobagent.cli.app import app
from jobagent.connectors.mock import MockJobSource
from jobagent.jobs.deduplication import JobDeduplicator
from jobagent.jobs.normalization import JobNormalizer
from jobagent.schemas.candidate import CandidateProfile, Confidence, EvidenceItem, EvidenceType
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
