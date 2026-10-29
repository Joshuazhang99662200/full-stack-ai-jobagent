"""Ratio-only diagnosis and confirmed-rule review; no activation or sending authority."""

from datetime import datetime
from decimal import Decimal

from jobagent.jobs.jd_snapshot import canonical_digest
from jobagent.jobs.job_intake import reject
from jobagent.jobs.pipeline_metrics import EXCLUSION_REASONS, metric_slice, rate, same_slice
from jobagent.schemas.pipeline import PipelineState
from jobagent.schemas.pipeline_metrics import (
    PipelineDiagnosis,
    PipelineDiagnosisCode,
    PipelineDiagnosisDecision,
    PipelineDiagnosisRequest,
    PipelineMetricEvidence,
    PipelineStageMetric,
)

DECLINE_FACTOR = Decimal("0.8")
Segment = tuple[PipelineState, PipelineState]
READ: Segment = ("greeting_sent", "greeting_read")
REPLY: Segment = ("greeting_read", "initial_contact")
CONTACT: Segment = ("greeting_sent", "initial_contact")
RESUME: Segment = ("resume_sent", "interview_pending")


def _low(metric: PipelineStageMetric | None) -> bool:
    return bool(
        metric is not None
        and metric.historical_rate is not None
        and metric.sliced_cumulative_rate is not None
        and metric.sliced_cumulative_rate < metric.historical_rate * DECLINE_FACTOR
    )


def _normal(metric: PipelineStageMetric | None) -> bool:
    return bool(
        metric is not None
        and metric.historical_rate is not None
        and metric.sliced_cumulative_rate is not None
        and metric.sliced_cumulative_rate >= metric.historical_rate * DECLINE_FACTOR
    )


def _persistent(metric: PipelineStageMetric, previous: list[PipelineStageMetric]) -> bool:
    adjacent = [
        value
        for value in previous
        if (value.stage_from, value.stage_to) == (metric.stage_from, metric.stage_to)
        and same_slice(value, metric)
        and value.window_end == metric.window_start
    ]
    if len({value.metric_id for value in adjacent}) > 1:
        reject("Choose one authoritative prior metric revision for a closed cumulative window.")
    return _low(metric) and any(_low(value) for value in adjacent)


def _validate(
    request: PipelineDiagnosisRequest, now: datetime
) -> tuple[dict[Segment, PipelineStageMetric], dict[str, PipelineMetricEvidence], str]:
    if now.tzinfo is None or any(value.window_end > now for value in request.current):
        reject("Diagnoses require closed cumulative windows and aware observation time.")
    first = request.current[0]
    current: dict[Segment, PipelineStageMetric] = {}
    for metric in request.current:
        if (
            not same_slice(metric, first)
            or metric.window_start != first.window_start
            or metric.window_end != first.window_end
        ):
            reject("One diagnosis request must use the same exact slice and cumulative window.")
        segment = (metric.stage_from, metric.stage_to)
        if segment in current and current[segment] != metric:
            reject("A funnel segment cannot use conflicting current metric revisions.")
        current[segment] = metric
    proofs: dict[str, PipelineMetricEvidence] = {}
    for item in request.evidence:
        if item.candidate_id != request.candidate_id:
            reject("Metric evidence belongs to another candidate.")
        if item.metric_id in proofs and proofs[item.metric_id] != item:
            reject("Metric evidence ID has conflicting cumulative counts.")
        proofs[item.metric_id] = item
    sources = set()
    for metric in current.values():
        proof = proofs.get(metric.metric_id)
        if proof is None:
            reject("Every current cumulative metric needs its original calculation evidence.")
        assert proof is not None
        sources.add(proof.source_digest)
        if (
            proof.cumulative_counts.numerator != metric.numerator
            or proof.cumulative_counts.denominator != metric.denominator
            or rate(proof.historical_counts) != metric.historical_rate
            or rate(proof.cumulative_counts) != metric.sliced_cumulative_rate
            or rate(proof.window_counts) != metric.window_rate
            or (None if proof.optimized_counts is None else rate(proof.optimized_counts))
            != metric.optimized_rate
        ):
            reject("Rates must match their recorded baseline, cumulative and window evidence.")
        if len(set(proof.cohort_job_ids)) != metric.denominator:
            reject(
                "Cumulative cohort IDs must identify each independent denominator job exactly once."
            )
        for reason in EXCLUSION_REASONS:
            jobs = proof.exclusion_job_ids.get(reason, [])
            if len(set(jobs)) != getattr(proof.excluded_counts, reason):
                reject("Exclusion counts require their distinct original job references.")
        if metric.denominator and not proof.evidence_references:
            reject("A nonempty cohort needs its source evidence references.")
    if len(sources) != 1:
        reject("Companion funnel segments must come from one coherent metric calculation snapshot.")
    if any(value.window_end > first.window_start for value in request.previous):
        reject("Prior cumulative evidence cannot overlap or follow the current window.")
    if request.rule is not None and (
        request.rule.candidate_id != request.candidate_id
        or request.rule.scope != metric_slice(first)
        or request.rule.effective_at >= first.window_end
        or request.rule.confirmed_at > now
    ):
        reject(
            "Optimization review must bind an existing owner-confirmed rule in this exact scope."
        )
    context = {
        "candidate_id": request.candidate_id,
        "current": [
            value.model_dump(mode="json")
            for value in sorted(current.values(), key=lambda x: x.metric_id)
        ],
        "previous": [
            value.model_dump(mode="json")
            for value in sorted(request.previous, key=lambda x: x.metric_id)
        ],
        "evidence": [
            value.model_dump(mode="json")
            for value in sorted(proofs.values(), key=lambda x: x.metric_id)
        ],
        "exclusions_reviewed": request.exclusions_reviewed,
        "review_reference": request.review_reference,
        "rule": request.rule.model_dump(mode="json") if request.rule else None,
    }
    return current, proofs, canonical_digest(context)


def _diagnosis(
    request: PipelineDiagnosisRequest,
    metric: PipelineStageMetric,
    proof: PipelineMetricEvidence,
    code: PipelineDiagnosisCode,
    source_digest: str,
) -> PipelineDiagnosis:
    identity = canonical_digest([source_digest, metric.metric_id, code])[7:31].upper()
    return PipelineDiagnosis(
        **metric_slice(metric).model_dump(exclude={"schema_version"}),
        diagnosis_id="DIAG_" + identity,
        candidate_id=request.candidate_id,
        metric_id=metric.metric_id,
        window_start=metric.window_start,
        window_end=metric.window_end,
        stage_from=metric.stage_from,
        stage_to=metric.stage_to,
        historical_rate=metric.historical_rate,
        sliced_cumulative_rate=metric.sliced_cumulative_rate,
        optimized_rate=metric.optimized_rate,
        numerator=metric.numerator,
        denominator=metric.denominator,
        excluded_counts=proof.excluded_counts,
        diagnosis_code=code,
        evidence_references=sorted(
            {
                metric.metric_id,
                *proof.evidence_references,
                *(value.metric_id for value in request.previous),
                *([request.review_reference] if request.review_reference else []),
            }
        ),
        source_digest=source_digest,
        rule_id=request.rule.rule_id if request.rule else None,
        pre_rule_cumulative_rate=request.rule.pre_rule_cumulative_rate if request.rule else None,
    )


def diagnose(request: PipelineDiagnosisRequest, *, now: datetime) -> PipelineDiagnosisDecision:
    """Compare cumulative rates only; absolute counts are checked solely for evidence integrity.

    A sustained drop means both the current and immediately preceding closed
    cumulative windows are below their own historical rate times 0.8. No absolute
    sample-size threshold applies. Unknown baselines or unreviewed causes require
    observation rather than guessed attribution. Rule reviews emit evidence for
    a rollback proposal; this function never confirms or revokes any rule.
    """
    request = PipelineDiagnosisRequest.model_validate(request.model_dump())
    current, proofs, source_digest = _validate(request, now)
    observations: set[str] = set()
    diagnoses: list[PipelineDiagnosis] = []

    def result() -> PipelineDiagnosisDecision:
        return PipelineDiagnosisDecision(
            diagnoses=diagnoses,
            observation_reasons=sorted(observations),
            source_digest=source_digest,
        )

    if not request.exclusions_reviewed and any(
        any(
            getattr(proof.excluded_counts, reason)
            for reason in EXCLUSION_REASONS
            if reason != "proof_pending"
        )
        for metric_id, proof in proofs.items()
        if metric_id in {m.metric_id for m in current.values()}
    ):
        observations.add("confounding_causes_require_review")
        return result()

    if request.rule is not None:
        target = current.get((request.rule.stage_from, request.rule.stage_to))
        if target is None:
            reject("Confirmed-rule review is missing its exact target funnel segment.")
        assert target is not None
        if target.optimized_rate is None or target.historical_rate is None:
            observations.add("optimized_cohort_or_historical_baseline_unknown")
            return result()
        code: PipelineDiagnosisCode = (
            "optimization_effective"
            if target.optimized_rate > target.historical_rate
            and target.optimized_rate > request.rule.pre_rule_cumulative_rate
            else "optimization_ineffective"
        )
        diagnoses.append(_diagnosis(request, target, proofs[target.metric_id], code, source_digest))
        return result()

    read, reply, contact, resume = (current.get(key) for key in (READ, REPLY, CONTACT, RESUME))
    if _low(read) and _normal(reply):
        assert read is not None
        if _persistent(read, request.previous):
            diagnoses.append(
                _diagnosis(
                    request, read, proofs[read.metric_id], "funnel_blocked_at_read", source_digest
                )
            )
        else:
            observations.add("read_decline_not_persistent_across_closed_cumulative_windows")
    elif _low(reply) or _low(read):
        target = reply if _low(reply) else read
        assert target is not None
        if not _normal(resume):
            observations.add("resume_companion_not_verified_normal")
        elif not _persistent(target, request.previous):
            observations.add("greeting_decline_not_persistent_across_closed_cumulative_windows")
        elif _low(reply):
            diagnoses.append(
                _diagnosis(
                    request, target, proofs[target.metric_id], "greeting_issue", source_digest
                )
            )
        else:
            observations.add("post_read_reply_companion_unknown")
    if _low(resume):
        assert resume is not None
        if not _normal(contact):
            observations.add("greeting_total_companion_not_verified_normal")
        elif not _persistent(resume, request.previous):
            observations.add("resume_decline_not_persistent_across_closed_cumulative_windows")
        else:
            diagnoses.append(
                _diagnosis(request, resume, proofs[resume.metric_id], "resume_issue", source_digest)
            )
    return result()
