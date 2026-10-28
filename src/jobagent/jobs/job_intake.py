"""Pure hand-off selection for independent greeting and learning branches."""

from typing import Never

from jobagent.errors import ContractValidationError
from jobagent.jobs.jd_snapshot import canonical_digest
from jobagent.schemas.job_intake import IntakeRecord, IntakeRequest


def target_key(request: IntakeRequest) -> str:
    target = (
        ["id", request.source_job_id]
        if request.source_job_id
        else ["url", str(request.job_url)]
        if request.job_url
        else [
            "reference",
            request.message_reference,
            request.list_version,
            request.target_reference,
        ]
    )
    return canonical_digest([request.candidate_id, request.domain, request.platform, target])


def next_actions(record: IntakeRecord) -> list[str]:
    if record.closed or record.merged_into:
        return []
    if record.paused:
        return ["owner_resume"]
    if record.job_id is None and record.listing is None:
        return ["resolve_target"]
    if record.snapshot_id is None:
        return ["fetch_full_jd"]
    actions = []
    if record.feature_set_id is None:
        actions.append("factorize")
    elif record.plan_id is None:
        actions.append("refresh_strategy")
    if record.contacted:
        actions.append("continue_conversation")
    elif any(request.intent == "draft" for request in record.requests):
        if record.draft is None:
            actions.append("generate_greeting")
        elif record.review is None:
            actions.append("independent_review")
        elif not record.review.accepted:
            actions.append("revise_greeting")
        elif record.batch_id is None:
            actions.append("prepare_outreach_batch")
        else:
            actions.append("existing_outreach_gate")
    return actions


def public_state(record: IntakeRecord) -> dict[str, object]:
    return {
        **record.model_dump(mode="json", exclude={"requests", "draft", "filter_context", "review"}),
        "source_references": [request.message_reference for request in record.requests],
        "next_actions": next_actions(record),
        "review_accepted": record.review.accepted if record.review else None,
        "grants_delivery_permission": False,
    }


def reject(message: str) -> Never:
    raise ContractValidationError(message)
