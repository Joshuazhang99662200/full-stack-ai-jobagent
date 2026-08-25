"""JSON-first commands for read-only Job Intelligence."""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Annotated, Any, Never, TypeVar

import typer
from pydantic import TypeAdapter, ValidationError

from jobagent.capabilities import ReasoningOutputT
from jobagent.connectors.liepin import LiepinCliJobSource
from jobagent.connectors.mock import MockJobSource
from jobagent.errors import ContractValidationError, JobAgentError, JobNotFoundError
from jobagent.jobs.deduplication import JobDeduplicator
from jobagent.jobs.hard_filter import HardFilterEngine
from jobagent.jobs.matching import MatchAggregator
from jobagent.jobs.normalization import JobNormalizer
from jobagent.jobs.ports import JobDiscoverySource, JobListingSource
from jobagent.jobs.query_derivation import SearchQueryDeriver
from jobagent.jobs.ranking import JobRanker
from jobagent.jobs.workflow import JobIntelligenceWorkflow
from jobagent.reasoning.job_matcher import ReasoningJobMatcher
from jobagent.reasoning.job_requirements import ReasoningJobRequirementExtractor
from jobagent.schemas.common import ContractModel
from jobagent.schemas.job_intelligence import (
    CandidateFilterContext,
    DeduplicationPolicy,
    JobAssessment,
    JobIntelligencePolicies,
    JobSearchQuery,
    MatchThresholdPolicy,
    RequirementMatchSet,
)
from jobagent.schemas.jobs import JobRequirementProfile, NormalizedJob
from jobagent.storage.candidate_repository import SqliteCandidateRepository
from jobagent.storage.database import Database
from jobagent.storage.job_repository import SqliteJobRepository

DEFAULT_DATABASE = Path(".jobagent/jobagent.sqlite3")
DEFAULT_FIXTURE = Path(__file__).parents[1] / "connectors" / "fixtures" / "jobs.json"
DatabaseOption = Annotated[Path, typer.Option("--database", help="Local SQLite path.")]
FixtureOption = Annotated[Path, typer.Option("--fixture", help="Synthetic source JSON path.")]

MOCK_CONNECTOR = "mock"
LIEPIN_CONNECTOR = "liepin"
SourceOption = Annotated[
    str,
    typer.Option(
        "--source",
        help="Read-only discovery connector: 'mock' (synthetic fixture) or 'liepin' (liepin-cli).",
    ),
]
ModelT = TypeVar("ModelT", bound=ContractModel)

jobs_app = typer.Typer(
    help="Search and evaluate jobs locally with typed, read-only intelligence.",
    no_args_is_help=True,
)


def _fail(error: JobAgentError) -> Never:
    typer.echo(
        json.dumps(
            {"error": {"code": error.code, "message": error.message, "details": error.details}},
            ensure_ascii=False,
        )
    )
    raise typer.Exit(code=1)


def _input_error(message: str) -> Never:
    _fail(ContractValidationError(message))


def _load_model(path: Path, model_type: type[ModelT]) -> ModelT:
    try:
        return model_type.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise ContractValidationError(
            "Reviewed JSON input could not be loaded.",
            details={"file_name": path.name, "contract": model_type.__name__},
        ) from error


def _load_assessments(path: Path) -> list[JobAssessment]:
    try:
        return TypeAdapter(list[JobAssessment]).validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise ContractValidationError(
            "Job assessments JSON could not be loaded.",
            details={"file_name": path.name},
        ) from error


def _emit_model(value: ContractModel) -> None:
    typer.echo(value.model_dump_json(indent=2))


def _emit_models(values: Sequence[ContractModel]) -> None:
    typer.echo(
        json.dumps(
            [value.model_dump(mode="json") for value in values],
            ensure_ascii=False,
            indent=2,
        )
    )


def _source(path: Path, connector: str = MOCK_CONNECTOR) -> JobDiscoverySource:
    if connector == MOCK_CONNECTOR:
        return MockJobSource.from_path(path)
    if connector == LIEPIN_CONNECTOR:
        raise ContractValidationError(
            "Liepin publishes no JD text in search results, so it cannot produce a "
            "full job observation. Use `jobagent jobs listings` instead.",
            details={"connector": connector, "use_instead": "jobs listings"},
        )
    raise ContractValidationError(
        "Unknown job discovery connector.",
        details={"connector": connector, "known": [MOCK_CONNECTOR, LIEPIN_CONNECTOR]},
    )


def _listing_source(connector: str) -> JobListingSource:
    if connector == LIEPIN_CONNECTOR:
        return LiepinCliJobSource()
    raise ContractValidationError(
        "Unknown job listing connector.",
        details={"connector": connector, "known": [LIEPIN_CONNECTOR]},
    )


def _normalized_job(
    source_job_id: str, fixture: Path, connector: str = MOCK_CONNECTOR
) -> NormalizedJob:
    return JobNormalizer().normalize(_source(fixture, connector).fetch_job(source_job_id))


def _repositories(
    path: Path,
) -> tuple[SqliteCandidateRepository, SqliteJobRepository]:
    path.parent.mkdir(parents=True, exist_ok=True)
    database = Database(path)
    database.migrate()
    return SqliteCandidateRepository(database), SqliteJobRepository(database)


class _ReviewedProvider:
    def __init__(self, value: ContractModel) -> None:
        self.value = value

    def generate(
        self,
        *,
        prompt_id: str,
        context: Mapping[str, Any],
        output_type: type[ReasoningOutputT],
    ) -> ReasoningOutputT:
        del prompt_id, context
        return output_type.model_validate(self.value.model_dump(mode="python"))


class _ReviewedDirectoryProvider:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def generate(
        self,
        *,
        prompt_id: str,
        context: Mapping[str, Any],
        output_type: type[ReasoningOutputT],
    ) -> ReasoningOutputT:
        job_id = str(context["job_id"])
        suffix = "requirements" if prompt_id == "job.requirements.extract.v1" else "matches"
        path = self.directory / f"{job_id}.{suffix}.json"
        try:
            return output_type.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as error:
            raise ContractValidationError(
                "Reviewed pipeline input could not be loaded.",
                details={"file_name": path.name, "prompt_id": prompt_id},
            ) from error


def _validated_requirements(
    source_job_id: str,
    reviewed_path: Path,
    fixture: Path,
) -> tuple[NormalizedJob, JobRequirementProfile]:
    job = _normalized_job(source_job_id, fixture)
    reviewed = _load_model(reviewed_path, JobRequirementProfile)
    return job, ReasoningJobRequirementExtractor(_ReviewedProvider(reviewed)).extract(job)


@jobs_app.command("listings")
def listings(
    query: Annotated[str, typer.Argument(help="Job-title keyword.")] = "",
    source: SourceOption = LIEPIN_CONNECTOR,
    location: Annotated[str | None, typer.Option("--location")] = None,
    company: Annotated[str | None, typer.Option("--company")] = None,
) -> None:
    """Search a listing source that publishes no JD text.

    Listings drive discovery and hard filters only. Tailoring still needs the JD.
    """
    try:
        results = _listing_source(source).search_listings(
            JobSearchQuery(query=query, company=company, location=location)
        )
        _emit_models(list(results))
    except JobAgentError as error:
        _fail(error)


@jobs_app.command("suggest-queries")
def suggest_queries(
    candidate_id: str,
    database: DatabaseOption = DEFAULT_DATABASE,
    location: Annotated[str | None, typer.Option("--location")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=50)] = 10,
) -> None:
    """Derive ranked search terms from the candidate's confirmed knowledge base."""
    try:
        candidates, _ = _repositories(database)
        profile = candidates.get_profile(candidate_id)
        if profile is None:
            raise JobNotFoundError(
                "Candidate profile was not found.",
                details={"candidate_id": candidate_id},
            )
        evidence = candidates.list_evidence(candidate_id)
        deriver = SearchQueryDeriver(max_suggestions=limit)
        _emit_model(deriver.derive(profile, evidence, location=location))
    except JobAgentError as error:
        _fail(error)


@jobs_app.command("search")
def search(
    query: Annotated[str, typer.Argument(help="Case-insensitive AND-token query.")] = "",
    fixture: FixtureOption = DEFAULT_FIXTURE,
    source: SourceOption = MOCK_CONNECTOR,
    title: Annotated[str | None, typer.Option("--title")] = None,
    company: Annotated[str | None, typer.Option("--company")] = None,
    location: Annotated[str | None, typer.Option("--location")] = None,
) -> None:
    """Search read-only source observations and emit source contracts."""
    try:
        results = _source(fixture, source).search(
            JobSearchQuery(query=query, title=title, company=company, location=location)
        )
        _emit_models(list(results))
    except JobAgentError as error:
        _fail(error)


@jobs_app.command("fetch")
def fetch(
    source_job_id: str,
    fixture: FixtureOption = DEFAULT_FIXTURE,
    source: SourceOption = MOCK_CONNECTOR,
) -> None:
    """Fetch one source observation by source ID."""
    try:
        _emit_model(_source(fixture, source).fetch_job(source_job_id))
    except JobAgentError as error:
        _fail(error)


@jobs_app.command("normalize")
def normalize(
    source_job_id: str,
    fixture: FixtureOption = DEFAULT_FIXTURE,
    source: SourceOption = MOCK_CONNECTOR,
) -> None:
    """Normalize one source observation deterministically."""
    try:
        _emit_model(_normalized_job(source_job_id, fixture, source))
    except JobAgentError as error:
        _fail(error)


@jobs_app.command("dedupe")
def dedupe(
    source_job_ids: Annotated[list[str], typer.Argument(help="Source job IDs to compare.")],
    fixture: FixtureOption = DEFAULT_FIXTURE,
    near_threshold: Annotated[float, typer.Option("--near-threshold", min=0.0, max=1.0)] = 0.85,
) -> None:
    """Merge duplicate observations while retaining every provenance record."""
    try:
        source = _source(fixture)
        jobs = [JobNormalizer().normalize(source.fetch_job(item)) for item in source_job_ids]
        result = JobDeduplicator().deduplicate(
            jobs,
            DeduplicationPolicy(near_duplicate_threshold=near_threshold),
        )
        _emit_model(result)
    except (JobAgentError, ValidationError) as error:
        if isinstance(error, JobAgentError):
            _fail(error)
        _input_error("Deduplication policy is invalid.")


@jobs_app.command("requirements")
def requirements(
    source_job_id: str,
    reviewed_requirements: Path,
    fixture: FixtureOption = DEFAULT_FIXTURE,
) -> None:
    """Revalidate reviewed requirement JSON against the exact job description."""
    try:
        _, profile = _validated_requirements(source_job_id, reviewed_requirements, fixture)
        _emit_model(profile)
    except JobAgentError as error:
        _fail(error)


@jobs_app.command("filter")
def filter_job(
    source_job_id: str,
    reviewed_requirements: Path,
    filter_context: Path,
    fixture: FixtureOption = DEFAULT_FIXTURE,
) -> None:
    """Run deterministic candidate hard constraints for one job."""
    try:
        job, profile = _validated_requirements(source_job_id, reviewed_requirements, fixture)
        context = _load_model(filter_context, CandidateFilterContext)
        _emit_model(
            HardFilterEngine().evaluate(
                job, profile, context, JobIntelligencePolicies().hard_filter
            )
        )
    except JobAgentError as error:
        _fail(error)


@jobs_app.command("match")
def match(
    source_job_id: str,
    reviewed_requirements: Path,
    reviewed_mappings: Path,
    candidate_id: str,
    database: DatabaseOption = DEFAULT_DATABASE,
    fixture: FixtureOption = DEFAULT_FIXTURE,
) -> None:
    """Revalidate reviewed mappings and compute a deterministic match result."""
    try:
        job, profile = _validated_requirements(source_job_id, reviewed_requirements, fixture)
        candidate_repository, _ = _repositories(database)
        if candidate_repository.get_profile(candidate_id) is None:
            raise ContractValidationError(
                "Candidate profile was not found.", details={"candidate_id": candidate_id}
            )
        evidence = candidate_repository.list_evidence(candidate_id)
        reviewed = _load_model(reviewed_mappings, RequirementMatchSet)
        mappings = ReasoningJobMatcher(_ReviewedProvider(reviewed)).map(
            job, profile, candidate_id, evidence
        )
        result = MatchAggregator().aggregate(
            profile,
            mappings,
            evidence,
            MatchThresholdPolicy(),
        )
        _emit_model(result)
    except JobAgentError as error:
        _fail(error)


@jobs_app.command("rank")
def rank(assessments_path: Path) -> None:
    """Rank reviewed job assessments with stable deterministic ordering."""
    try:
        _emit_models(JobRanker().rank(_load_assessments(assessments_path)))
    except JobAgentError as error:
        _fail(error)


@jobs_app.command("pipeline")
def pipeline(
    candidate_id: str,
    filter_context: Path,
    reviewed_directory: Path,
    query: Annotated[str, typer.Option("--query")] = "",
    database: DatabaseOption = DEFAULT_DATABASE,
    fixture: FixtureOption = DEFAULT_FIXTURE,
) -> None:
    """Run the complete offline intelligence pipeline from reviewed JSON inputs."""
    try:
        context = _load_model(filter_context, CandidateFilterContext)
        provider = _ReviewedDirectoryProvider(reviewed_directory)
        candidate_repository, job_repository = _repositories(database)
        workflow = JobIntelligenceWorkflow(
            source=_source(fixture),
            normalizer=JobNormalizer(),
            deduplicator=JobDeduplicator(),
            requirement_extractor=ReasoningJobRequirementExtractor(provider),
            hard_filter=HardFilterEngine(),
            matcher=ReasoningJobMatcher(provider),
            aggregator=MatchAggregator(),
            ranker=JobRanker(),
            candidate_repository=candidate_repository,
            job_repository=job_repository,
        )
        _emit_model(
            workflow.run(
                JobSearchQuery(query=query),
                candidate_id,
                context,
                JobIntelligencePolicies(),
            )
        )
    except JobAgentError as error:
        _fail(error)
