"""Pure cumulative funnel cohorts; no storage, host calls, or sample-size diagnosis gate."""

from datetime import datetime
from decimal import Decimal
from typing import get_args

from jobagent.jobs.jd_snapshot import canonical_digest
from jobagent.jobs.job_intake import reject
from jobagent.schemas.pipeline import PipelineState
from jobagent.schemas.pipeline_metrics import (
    PIPELINE_FUNNEL_SEGMENTS,
    ExclusionReason,
    PipelineExclusionCounts,
    PipelineMetricEvidence,
    PipelineMetricFact,
    PipelineMetricRequest,
    PipelineMetricResult,
    PipelineRateCounts,
    PipelineSlice,
    PipelineStageMetric,
    SalaryBand,
)

SLICE_FIELDS = frozenset(PipelineSlice.model_fields) - {"schema_version"}
EXCLUSION_REASONS: tuple[ExclusionReason, ...] = get_args(ExclusionReason)


def salary_band(maximum_k: int | None) -> SalaryBand | None:
    """Fixed reporting bins, independent of the candidate's salary acceptance rule."""
    if maximum_k is None:
        return None
    if maximum_k < 0:
        reject("Salary reporting cannot bucket a negative maximum.")
    if maximum_k < 18:
        return "below18k"
    if maximum_k < 25:
        return "18-25k"
    if maximum_k < 40:
        return "25-40k"
    return "40k+"


def metric_slice(value: PipelineSlice) -> PipelineSlice:
    return PipelineSlice.model_validate(value.model_dump(include=set(SLICE_FIELDS)))


def same_slice(left: PipelineSlice, right: PipelineSlice) -> bool:
    return metric_slice(left) == metric_slice(right)


def matches_scope(fact: PipelineMetricFact, scope: PipelineSlice) -> bool:
    actual = metric_slice(fact)
    if scope.dimension_platform == "all":
        actual = actual.model_copy(update={"dimension_platform": "all"})
    return actual == scope


def rate(counts: PipelineRateCounts) -> Decimal | None:
    return Decimal(counts.numerator) / counts.denominator if counts.denominator else None


def _identity(fact: PipelineMetricFact) -> tuple[str, str]:
    # job_id carries a source prefix, but platform is also explicit for auditability.
    return fact.dimension_platform, fact.job_id.casefold()


def _facts(
    request: PipelineMetricRequest, facts: list[PipelineMetricFact], now: datetime
) -> list[PipelineMetricFact]:
    unique: dict[str, PipelineMetricFact] = {}
    for raw in facts:
        fact = PipelineMetricFact.model_validate(raw.model_dump())
        if fact.candidate_id != request.candidate_id or not matches_scope(fact, request.scope):
            continue
        if any(value > now for value in fact.stage_times.values()):
            reject("A funnel fact cannot claim a future observed stage.")
        for source, target in PIPELINE_FUNNEL_SEGMENTS:
            if (
                source in fact.stage_times
                and target in fact.stage_times
                and fact.stage_times[target] < fact.stage_times[source]
            ):
                reject("Conversion evidence must follow the source stage in the same round.")
        if fact.pipeline_id in unique and fact != unique[fact.pipeline_id]:
            reject("One immutable pipeline fact cannot have conflicting input versions.")
        unique[fact.pipeline_id] = fact
    return [unique[key] for key in sorted(unique)]


def _cohorts(
    facts: list[PipelineMetricFact], source: PipelineState, end: datetime
) -> list[PipelineMetricFact]:
    selected: dict[tuple[str, str], PipelineMetricFact] = {}
    for fact in facts:
        entered = fact.stage_times.get(source)
        if (
            entered is None
            or entered >= end
            or (source != "draft_pending" and not fact.proof_verified)
        ):
            continue
        key = _identity(fact)
        old = selected.get(key)
        if old is None or (entered, fact.pipeline_id) < (old.stage_times[source], old.pipeline_id):
            selected[key] = fact
    return [selected[key] for key in sorted(selected)]


def _count(
    cohort: list[PipelineMetricFact],
    source: PipelineState,
    target: PipelineState,
    end: datetime,
    lower: datetime | None = None,
) -> PipelineRateCounts:
    members = [
        fact
        for fact in cohort
        if fact.stage_times[source] < end and (lower is None or fact.stage_times[source] >= lower)
    ]
    numerator = sum(
        fact.proof_verified and target in fact.stage_times and fact.stage_times[target] < end
        for fact in members
    )
    return PipelineRateCounts(numerator=numerator, denominator=len(members))


def _exclusions(
    facts: list[PipelineMetricFact],
    cohort: list[PipelineMetricFact],
    source: PipelineState,
    end: datetime,
) -> dict[ExclusionReason, list[str]]:
    reasons: dict[ExclusionReason, dict[tuple[str, str], str]] = {
        reason: {} for reason in EXCLUSION_REASONS
    }
    verified = {_identity(fact) for fact in cohort if fact.proof_verified}
    for fact in cohort:
        reason = fact.exclusion_reason
        abandoned_at = fact.stage_times.get("abandoned")
        if reason is not None and (abandoned_at is None or abandoned_at < end):
            reasons[reason][_identity(fact)] = fact.job_id
    if source != "draft_pending":
        for fact in facts:
            entered = fact.stage_times.get("draft_pending")
            if (
                not fact.proof_verified
                and (
                    fact.exclusion_reason == "proof_pending" or "greeting_sent" in fact.stage_times
                )
                and entered is not None
                and entered < end
                and _identity(fact) not in verified
            ):
                reasons["proof_pending"][_identity(fact)] = fact.job_id
    return {reason: sorted(values.values()) for reason, values in reasons.items()}


def compute_metrics(
    request: PipelineMetricRequest, facts: list[PipelineMetricFact], *, now: datetime
) -> PipelineMetricResult:
    """Deduplicate canonical jobs and never borrow a conversion from a later contact round.

    Windows are [start, end). Each segment uses the first source-stage contact round
    for that canonical source job. Its destination must occur in that same round.
    Historical success is measured as of start, cumulative success as of end.
    Abandoned rows stay in the cohort; their causes are disclosed separately.
    """
    if now.tzinfo is None or request.window_end > now:
        reject("Metrics require an already closed window and an aware observation time.")
    selected = _facts(request, facts, now)
    source_digest = canonical_digest(
        [request.model_dump(mode="json"), [fact.model_dump(mode="json") for fact in selected]]
    )
    metrics: list[PipelineStageMetric] = []
    evidence: list[PipelineMetricEvidence] = []
    scope = request.scope.model_dump(exclude={"schema_version"})
    for source, target in PIPELINE_FUNNEL_SEGMENTS:
        cohort = _cohorts(selected, source, request.window_end)
        historical = _count(cohort, source, target, request.window_start)
        cumulative = _count(cohort, source, target, request.window_end)
        window = _count(cohort, source, target, request.window_end, request.window_start)
        optimized = (
            None
            if request.rule is None
            else _count(cohort, source, target, request.window_end, request.rule.effective_at)
        )
        identity = canonical_digest([source_digest, source, target])[7:23].upper()
        metric_id = "METRIC_" + identity + "_" + request.window_end.strftime("%Y%m%dT%H%M%S%fZ")
        metric = PipelineStageMetric(
            **scope,
            metric_id=metric_id,
            window_start=request.window_start,
            window_end=request.window_end,
            stage_from=source,
            stage_to=target,
            numerator=cumulative.numerator,
            denominator=cumulative.denominator,
            historical_rate=rate(historical),
            sliced_cumulative_rate=rate(cumulative),
            optimized_rate=None if optimized is None else rate(optimized),
            window_rate=rate(window),
            sample_count=cumulative.denominator,
            diagnosis_id=None,
        )
        exclusions = _exclusions(selected, cohort, source, request.window_end)
        detail = PipelineMetricEvidence(
            metric_id=metric_id,
            candidate_id=request.candidate_id,
            historical_counts=historical,
            cumulative_counts=cumulative,
            optimized_counts=optimized,
            window_counts=window,
            cohort_job_ids=[fact.job_id for fact in cohort],
            excluded_counts=PipelineExclusionCounts.model_validate(
                {reason: len(jobs) for reason, jobs in exclusions.items()}
            ),
            exclusion_job_ids=exclusions,
            evidence_references=sorted(
                {ref for fact in selected for ref in fact.evidence_references}
            ),
            source_digest=source_digest,
        )
        metrics.append(metric)
        evidence.append(detail)
    return PipelineMetricResult(metrics=metrics, evidence=evidence)
