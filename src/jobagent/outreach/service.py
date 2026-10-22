# ruff: noqa: RUF001  -- Chinese greetings carry full-width punctuation by design.
"""Batch first-contact outreach: list, ask, approve, then release one item at a time.

`Approval != Send`. Approving a numbered batch records which exact greetings a
person agreed to. Each send is then re-checked on its own: the approval must still
cover the item, the platform must not be halted today, the interval and the daily
cap must allow it, and this session must hold the platform's lease. The host does
the clicking; this service only decides whether the next click may happen.
"""

import hashlib
import json
from collections.abc import Collection, Mapping, Sequence
from datetime import UTC, datetime, timedelta, timezone

from jobagent.errors import ApprovalRequiredError, StaleApprovalError
from jobagent.outreach.rules import first_greeting_problems
from jobagent.schemas.applications import ApprovalChannel
from jobagent.schemas.jobs import NormalizedJob
from jobagent.schemas.outreach import (
    OutreachApproval,
    OutreachAsk,
    OutreachAudit,
    OutreachBatch,
    OutreachDraft,
    OutreachDraftReport,
    OutreachItem,
    OutreachPolicy,
    OutreachRejection,
    OutreachResult,
    SendDecision,
)

# Daily caps and halts follow the boards' own calendar day.
PLATFORM_DAY = timezone(timedelta(hours=8))
_HALTING = frozenset({OutreachResult.FAILED, OutreachResult.INTERVENTION})
_COUNTS_AS_CONTACT = frozenset({OutreachResult.SENT, OutreachResult.DUPLICATE_FOUND})


def _digest(value: object) -> str:
    canonical = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _job_content(job: NormalizedJob) -> object:
    return job.model_dump(mode="json", exclude={"collected_at"})


def _item_digest(job: NormalizedJob, draft: OutreachDraft) -> str:
    content: dict[str, object] = {
        "job": _job_content(job),
        "platform": draft.platform,
        "text": draft.text,
    }
    tags = {
        name: value
        for name, value in (
            ("variant", draft.variant),
            ("hook_requirement", draft.hook_requirement),
            ("experiment_id", draft.experiment_id),
        )
        if value is not None
    }
    # Untagged items keep the digest they always had, so stored batches stay valid.
    if tags:
        content["tags"] = tags
    if draft.written_by == "person":
        content["written_by"] = "person"
    return _digest(content)


def policy_digest(policy: OutreachPolicy) -> str:
    return _digest(policy.model_dump(mode="json"))


def contacted_job_ids(audits: Sequence[OutreachAudit]) -> set[str]:
    """Jobs a first greeting has reached, or was found to have reached already."""
    return {audit.job_id for audit in audits if audit.result in _COUNTS_AS_CONTACT}


# Greetings go to strong matches first, then possible ones, then jobs never
# assessed (a person brought them). Weak and non-matches are reported, not drafted.
TIER_ORDER = {"hand_picked": 0, "strong_match": 1, "possible_match": 2, None: 3}
TIER_LABELS = {
    "hand_picked": "你挑的",
    "strong_match": "强匹配",
    "possible_match": "可能匹配",
    None: "未评估",
}
UNDRAFTED_TIERS = frozenset({"weak_match", "no_match"})


class OutreachService:
    def build_batch(
        self,
        drafts: Sequence[OutreachDraft],
        *,
        jobs: Mapping[str, NormalizedJob],
        already_contacted: Collection[str],
        confirmed_evidence_ids: Collection[str],
        batch_id: str,
        created_at: datetime,
        policy: OutreachPolicy | None = None,
        match_tiers: Mapping[str, str] | None = None,
        preferences: Mapping[str, float] | None = None,
        possible_match_min_preference: float | None = None,
        harness_version: str | None = None,
    ) -> OutreachDraftReport:
        """List the drafts that pass every rule; return the rest with their reasons.

        Items are ordered by match tier: strong, possible, then never assessed.
        """
        policy = policy or OutreachPolicy()
        tiers = match_tiers or {}
        items: list[OutreachItem] = []
        rejected: list[OutreachRejection] = []
        listed: set[str] = set()
        ordered = sorted(
            enumerate(drafts), key=lambda pair: TIER_ORDER.get(tiers.get(pair[1].job_id), 3)
        )
        for index, draft in ordered:
            tier = tiers.get(draft.job_id)
            reasons = self._draft_problems(
                draft, jobs, already_contacted, confirmed_evidence_ids, listed
            )
            if tier in UNDRAFTED_TIERS:
                reasons = [*reasons, tier]
            elif (
                tier == "possible_match"
                and possible_match_min_preference is not None
                and (preferences or {}).get(draft.job_id, 0.0) < possible_match_min_preference
            ):
                # Possible matches are only worth a first message when they speak to
                # the themes the person asked for.
                reasons = [*reasons, "low_preference"]
            if not reasons and len(items) >= policy.max_items_per_batch:
                reasons = ["batch_full"]
            if reasons:
                rejected.append(
                    OutreachRejection(index=index, job_id=draft.job_id, reasons=reasons)
                )
                continue
            job = jobs[draft.job_id]
            listed.add(draft.job_id)
            items.append(
                OutreachItem(
                    number=len(items) + 1,
                    job_id=job.id,
                    platform=draft.platform,
                    company=job.company,
                    title=job.title,
                    url=str(job.url),
                    text=draft.text,
                    evidence_ids=draft.evidence_ids,
                    match_tier=tier,
                    variant=draft.variant,
                    hook_requirement=draft.hook_requirement,
                    experiment_id=draft.experiment_id,
                    written_by=draft.written_by,
                    item_digest=_item_digest(job, draft),
                )
            )
        if not items:
            return OutreachDraftReport(rejected=rejected)
        return OutreachDraftReport(
            batch=OutreachBatch(
                batch_id=batch_id,
                items=items,
                policy=policy,
                policy_digest=policy_digest(policy),
                batch_digest=_digest([[item.number, item.item_digest] for item in items]),
                created_at=created_at,
                harness_version=harness_version,
            ),
            rejected=rejected,
        )

    @staticmethod
    def _draft_problems(
        draft: OutreachDraft,
        jobs: Mapping[str, NormalizedJob],
        already_contacted: Collection[str],
        confirmed_evidence_ids: Collection[str],
        listed: Collection[str],
    ) -> list[str]:
        job = jobs.get(draft.job_id)
        if job is None:
            return ["job_not_stored"]
        if draft.platform != job.source:
            return ["platform_mismatch"]
        if draft.job_id in already_contacted:
            return ["already_contacted"]
        if draft.job_id in listed:
            return ["duplicate_in_batch"]
        reasons = first_greeting_problems(
            draft.text, length_limit=draft.written_by != "person"
        )
        if any(evidence not in confirmed_evidence_ids for evidence in draft.evidence_ids):
            reasons.append("unconfirmed_evidence")
        return reasons

    def ask(self, batch: OutreachBatch, *, asked_at: datetime | None = None) -> OutreachAsk:
        """Put the numbered list to a person, word for word. This approves nothing."""
        lines = [
            f"{item.number}. 【{TIER_LABELS.get(item.match_tier, item.match_tier)}】"
            f"{item.platform}｜{item.company}｜{item.title}"
            f"{'（本人改写）' if item.written_by == 'person' else ''}\n   {item.text}"
            for item in batch.items
        ]
        question = (
            f"以下 {len(batch.items)} 条首条招呼，回复要发送的编号（例如：发 1-20、23）：\n"
            + "\n".join(lines)
        )
        return OutreachAsk(
            ask_id=f"OASK_{batch.batch_id.removeprefix('OBATCH_')}",
            batch_id=batch.batch_id,
            batch_digest=batch.batch_digest,
            policy_digest=batch.policy_digest,
            question=question,
            asked_at=asked_at or datetime.now(UTC),
        )

    def approve(
        self,
        batch: OutreachBatch,
        *,
        ask: OutreachAsk | None,
        numbers: Sequence[int],
        attestation: str,
        approved_at: datetime | None = None,
    ) -> OutreachApproval:
        """Record a person's answer to a question that was asked about this batch."""
        details = {"batch_id": batch.batch_id}
        if ask is None:
            raise ApprovalRequiredError(
                "An approval must answer a question that was posed first.", details=details
            )
        if not attestation.strip():
            raise ApprovalRequiredError(
                "An approval must carry the person's own answer.", details=details
            )
        if ask.batch_id != batch.batch_id or ask.batch_digest != batch.batch_digest:
            raise ApprovalRequiredError(
                "The list changed after the question was asked, so the answer was about "
                "something else.",
                details={**details, "ask_id": ask.ask_id},
            )
        if ask.policy_digest != batch.policy_digest:
            raise ApprovalRequiredError(
                "The pacing rules changed after the question was asked.", details=details
            )
        known = {item.number for item in batch.items}
        chosen = sorted(set(numbers))
        unknown = [number for number in chosen if number not in known]
        if not chosen or unknown:
            raise ApprovalRequiredError(
                "The approved numbers must come from the list that was shown.",
                details={**details, "unknown": unknown},
            )
        return OutreachApproval(
            approval_id=f"OAPPROVAL_{batch.batch_id.removeprefix('OBATCH_')}",
            batch_id=batch.batch_id,
            batch_digest=batch.batch_digest,
            policy_digest=batch.policy_digest,
            approved_numbers=chosen,
            channel=ApprovalChannel.AGENT_RELAY,
            attestation=attestation.strip(),
            ask_id=ask.ask_id,
            approved_at=approved_at or datetime.now(UTC),
        )

    def next_item(
        self,
        batch: OutreachBatch,
        approval: OutreachApproval,
        *,
        platform: str,
        audits: Sequence[OutreachAudit],
        lease_held: bool,
        now: datetime,
    ) -> SendDecision:
        """Decide whether one more greeting may go out on `platform` right now.

        `audits` are every outreach attempt on record, across batches, because caps,
        intervals and halts belong to the platform rather than to one batch.
        """
        policy = batch.policy
        if approval.batch_id != batch.batch_id or approval.batch_digest != batch.batch_digest:
            raise StaleApprovalError(
                "Approval no longer matches this batch.",
                details={"batch_id": batch.batch_id, "approval_id": approval.approval_id},
            )
        if approval.policy_digest != policy_digest(policy):
            raise StaleApprovalError(
                "Approval was given under different pacing rules.",
                details={"batch_id": batch.batch_id, "approval_id": approval.approval_id},
            )
        if not lease_held:
            return SendDecision(allowed=False, reason="lease_not_held")
        on_platform = [audit for audit in audits if audit.platform == platform]
        today = now.astimezone(PLATFORM_DAY).date()
        todays = [a for a in on_platform if a.recorded_at.astimezone(PLATFORM_DAY).date() == today]
        if any(audit.result in _HALTING for audit in todays):
            return SendDecision(allowed=False, reason="platform_halted_today")
        sent_today = sum(audit.result is OutreachResult.SENT for audit in todays)
        if sent_today >= policy.daily_cap_per_platform:
            return SendDecision(allowed=False, reason="daily_cap_reached")
        last = max((audit.recorded_at for audit in on_platform), default=None)
        if last is not None:
            elapsed = (now - last).total_seconds()
            if elapsed < policy.min_seconds_between_sends:
                return SendDecision(
                    allowed=False,
                    reason="too_soon",
                    wait_seconds=int(policy.min_seconds_between_sends - elapsed),
                )
        finished = {a.number for a in audits if a.batch_id == batch.batch_id}
        approved = set(approval.approved_numbers)
        for item in batch.items:
            if (
                item.platform == platform
                and item.number in approved
                and item.number not in finished
            ):
                return SendDecision(allowed=True, item=item)
        return SendDecision(allowed=False, reason="nothing_left")
