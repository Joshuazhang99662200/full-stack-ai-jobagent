"""Offline orchestration for read-only Job Intelligence."""

import hashlib
from collections.abc import Sequence

from jobagent.candidate.ports import CandidateRepository
from jobagent.errors import ContractValidationError
from jobagent.jobs.deduplication import JobDeduplicator
from jobagent.jobs.hard_filter import HardFilterEngine
from jobagent.jobs.matching import MatchAggregator
from jobagent.jobs.normalization import JobNormalizer
from jobagent.jobs.ports import (
    JobDiscoverySource,
    JobEvidenceMatcher,
    JobRepository,
    JobRequirementExtractor,
)
from jobagent.jobs.ranking import JobRanker
from jobagent.schemas.common import ContractModel
from jobagent.schemas.job_intelligence import (
    CandidateFilterContext,
    JobAssessment,
    JobIntelligencePolicies,
    JobIntelligenceRun,
    JobSearchQuery,
)
from jobagent.schemas.jobs import FilterDecision


def _digest_model(value: ContractModel) -> str:
    content = value.model_dump_json()
    return f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}"


def _digest_models(values: Sequence[ContractModel]) -> str:
    content = "\n".join(item.model_dump_json() for item in values)
    return f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}"


class JobIntelligenceWorkflow:
    """Run discovery through ranking while keeping every stage independently callable."""

    def __init__(
        self,
        *,
        source: JobDiscoverySource,
        normalizer: JobNormalizer,
        deduplicator: JobDeduplicator,
        requirement_extractor: JobRequirementExtractor,
        hard_filter: HardFilterEngine,
        matcher: JobEvidenceMatcher,
        aggregator: MatchAggregator,
        ranker: JobRanker,
        candidate_repository: CandidateRepository,
        job_repository: JobRepository,
    ) -> None:
        self.source = source
        self.normalizer = normalizer
        self.deduplicator = deduplicator
        self.requirement_extractor = requirement_extractor
        self.hard_filter = hard_filter
        self.matcher = matcher
        self.aggregator = aggregator
        self.ranker = ranker
        self.candidate_repository = candidate_repository
        self.job_repository = job_repository

    def run(
        self,
        query: JobSearchQuery,
        candidate_id: str,
        filter_context: CandidateFilterContext,
        policies: JobIntelligencePolicies,
    ) -> JobIntelligenceRun:
        if filter_context.candidate_id != candidate_id:
            raise ContractValidationError(
                "Job Intelligence filter context belongs to another candidate.",
                details={"candidate_id": candidate_id},
            )
        if self.candidate_repository.get_profile(candidate_id) is None:
            raise ContractValidationError(
                "Job Intelligence candidate profile was not found.",
                details={"candidate_id": candidate_id},
            )

        source_records = self.source.search(query)
        normalized = [self.normalizer.normalize(record) for record in source_records]
        deduplicated = self.deduplicator.deduplicate(normalized, policies.deduplication)
        evidence = self.candidate_repository.list_evidence(candidate_id)
        sorted_evidence = sorted(evidence, key=lambda item: item.id)
        evidence_digest = _digest_models(sorted_evidence)
        filter_policy_digest = _digest_model(policies.hard_filter)
        match_policy_digest = _digest_model(policies.match_thresholds)

        requirement_profiles = []
        filter_results = {}
        matches = {}
        assessments: list[JobAssessment] = []
        for job in deduplicated.jobs:
            self.job_repository.save_job(job)
            requirements = self.requirement_extractor.extract(job)
            requirements_digest = self.job_repository.save_requirements(requirements)
            requirement_profiles.append(requirements)
            filter_result = self.hard_filter.evaluate(
                job,
                requirements,
                filter_context,
                policies.hard_filter,
            )
            filter_results[job.id] = filter_result
            self.job_repository.save_filter_result(
                candidate_id,
                job.id,
                filter_policy_digest,
                filter_result,
            )
            if filter_result.decision is FilterDecision.REJECT:
                continue

            mappings = self.matcher.map(job, requirements, candidate_id, evidence)
            match_result = self.aggregator.aggregate(
                requirements,
                mappings,
                evidence,
                policies.match_thresholds,
            )
            matches[job.id] = match_result
            self.job_repository.save_match(
                candidate_id,
                job.id,
                evidence_digest=evidence_digest,
                requirements_digest=requirements_digest,
                policy_digest=match_policy_digest,
                result=match_result,
            )
            must_have_score = next(
                (
                    dimension.score
                    for dimension in match_result.dimensions
                    if dimension.dimension == "must_have"
                ),
                0.0,
            )
            assessments.append(
                JobAssessment(
                    job_id=job.id,
                    filter_result=filter_result,
                    match_result=match_result,
                    published_at=job.published_at,
                    must_have_score=must_have_score,
                )
            )

        return JobIntelligenceRun(
            candidate_id=candidate_id,
            query=query,
            normalized_jobs=deduplicated.jobs,
            requirements=requirement_profiles,
            filter_results=filter_results,
            matches=matches,
            ranked_jobs=self.ranker.rank(assessments),
        )
