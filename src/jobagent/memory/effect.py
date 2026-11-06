"""Reply outcomes of sent greetings and interval-based rate comparisons.

Pure: callers pass ledger facts and an explicit observation window and minimum
sample. Nothing here chooses those values, writes state or grants permission.
"""

import math
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Literal

from jobagent.errors import ContractValidationError
from jobagent.schemas.conversation import Conversation, ConversationEvent, EventKind
from jobagent.schemas.memory import (
    EffectGroup,
    MemoryEffectReport,
    RateComparison,
    ReplyOutcome,
    SentOutreach,
)
from jobagent.schemas.outreach import OutreachAudit, OutreachBatch, OutreachResult

Verdict = Literal["insufficient_sample", "higher", "lower", "no_clear_difference"]

# Two-sided 95% normal quantile; a statistical convention, not a personal setting.
Z_95 = 1.959963984540054


def reply_outcomes(
    items: Sequence[SentOutreach],
    threads: Sequence[tuple[Conversation, Sequence[ConversationEvent]]],
    *,
    now: datetime,
    window: timedelta,
) -> list[ReplyOutcome]:
    """A reply is a recruiter message on the same platform and job after the send.

    Items whose window has not closed are pending and stay out of every rate, even
    when a reply already arrived.
    """
    if now.tzinfo is None or window <= timedelta(0):
        raise ContractValidationError("Outcomes need an aware clock and a positive window.")
    inbound: dict[tuple[str, str], list[datetime]] = {}
    for conversation, events in threads:
        if conversation.job_id is None:
            continue
        key = (conversation.platform, conversation.job_id)
        inbound.setdefault(key, []).extend(
            event.inbound.received_at
            for event in events
            if event.kind is EventKind.INBOUND and event.inbound is not None
        )
    outcomes = []
    for item in items:
        deadline = item.sent_at + window
        received = inbound.get((item.platform, item.job_id), [])
        status: Literal["replied", "no_reply", "pending"]
        # Only closed windows count, replied or not: counting early replies from
        # open windows while excluding their silences would inflate every rate.
        if now < deadline:
            status = "pending"
        elif any(item.sent_at <= at <= deadline for at in received):
            status = "replied"
        else:
            status = "no_reply"
        outcomes.append(ReplyOutcome(**item.model_dump(), status=status))
    return outcomes


def wilson_interval(successes: int, total: int, z: float = Z_95) -> tuple[float, float]:
    if total <= 0 or not 0 <= successes <= total:
        raise ContractValidationError("A rate needs 0 <= successes <= total and total > 0.")
    rate = successes / total
    denominator = 1 + z * z / total
    centre = (rate + z * z / (2 * total)) / denominator
    half = z * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


def newcombe_difference(
    treated: tuple[int, int], baseline: tuple[int, int], z: float = Z_95
) -> tuple[float, float]:
    """Newcombe's hybrid score interval for treated minus baseline rate."""
    (k1, n1), (k2, n2) = treated, baseline
    p1, p2 = k1 / n1, k2 / n2
    l1, u1 = wilson_interval(k1, n1, z)
    l2, u2 = wilson_interval(k2, n2, z)
    difference = p1 - p2
    return (
        difference - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2),
        difference + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2),
    )


def compare_rates(
    treated: tuple[int, int], baseline: tuple[int, int], *, min_sample: int
) -> RateComparison:
    """Claim a difference only with enough closed samples and an interval excluding zero."""
    if min_sample < 1:
        raise ContractValidationError("The minimum sample must be explicit and positive.")
    (k1, n1), (k2, n2) = treated, baseline
    counts = RateComparison(
        treated_replies=k1, treated_sent=n1, baseline_replies=k2, baseline_sent=n2,
        difference=None, interval_low=None, interval_high=None, verdict="insufficient_sample",
    )
    if n1 < min_sample or n2 < min_sample:
        return counts
    low, high = newcombe_difference(treated, baseline)
    verdict: Verdict = "higher" if low > 0 else "lower" if high < 0 else "no_clear_difference"
    return counts.model_copy(update={
        "difference": k1 / n1 - k2 / n2, "interval_low": low, "interval_high": high,
        "verdict": verdict,
    })


def sent_from_ledger(
    candidate_id: str,
    *,
    batches: Sequence[OutreachBatch],
    audits: Sequence[OutreachAudit],
    owned_evidence_ids: set[str],
) -> list[SentOutreach]:
    """Positive send records for this candidate's items, with their memory provenance.

    Ownership comes from the source binding, or for older items from confirmed
    evidence; items that prove neither are left out rather than guessed.
    """
    items = {
        (batch.batch_id, item.number, item.item_digest): item
        for batch in batches
        for item in batch.items
    }
    result: dict[tuple[str, int], SentOutreach] = {}
    for audit in sorted(audits, key=lambda a: a.recorded_at):
        if audit.result is not OutreachResult.SENT:
            continue
        item = items.get((audit.batch_id, audit.number, audit.item_digest))
        if item is None:
            continue
        binding = item.source_binding
        if binding is not None:
            if binding.candidate_id != candidate_id:
                continue
        elif not item.evidence_ids or not set(item.evidence_ids) <= owned_evidence_ids:
            continue
        generation = binding.generation if binding is not None else None
        result.setdefault((audit.batch_id, audit.number), SentOutreach(
            batch_id=audit.batch_id, number=audit.number, job_id=item.job_id,
            platform=item.platform, sent_at=audit.recorded_at,
            memory_version=generation.memory_version if generation else None,
            preference_rule_ids=generation.preference_rule_ids if generation else [],
        ))
    return list(result.values())


def memory_effect_report(
    candidate_id: str,
    outcomes: Sequence[ReplyOutcome],
    *,
    window: timedelta,
    min_sample: int,
    observed_at: datetime,
) -> MemoryEffectReport:
    """Compare each memory version and rule against greetings made without memory."""
    closed = [o for o in outcomes if o.status != "pending"]

    def rate(group: Sequence[ReplyOutcome]) -> tuple[int, int]:
        return sum(o.status == "replied" for o in group), len(group)

    baseline = rate([o for o in closed if o.memory_version is None])
    groups = []
    for version in sorted({o.memory_version for o in closed if o.memory_version}):
        treated = [o for o in closed if o.memory_version == version]
        groups.append(EffectGroup(
            label=version, kind="memory_version",
            comparison=compare_rates(rate(treated), baseline, min_sample=min_sample),
        ))
        for rule in sorted({r for o in treated for r in o.preference_rule_ids}):
            groups.append(EffectGroup(
                label=f"{version}:{rule}", kind="rule",
                comparison=compare_rates(
                    rate([o for o in treated if rule in o.preference_rule_ids]), baseline,
                    min_sample=min_sample,
                ),
            ))
    return MemoryEffectReport(
        candidate_id=candidate_id, window_days=window.days, min_sample=min_sample,
        observed_at=observed_at, pending=len(outcomes) - len(closed), groups=groups,
    )
