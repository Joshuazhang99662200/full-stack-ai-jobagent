"""Count, from the outreach ledger, which memory versions and rules reached real items."""

from collections.abc import Mapping, Sequence

from jobagent.schemas.memory import (
    MemoryUsageReport,
    MemoryVersionUsage,
    PreferenceRuleUsage,
    UsageCounts,
)
from jobagent.schemas.outreach import OutreachApproval, OutreachAudit, OutreachBatch, OutreachResult


def _bump(counts: UsageCounts, *, approved: bool, sent: bool) -> None:
    counts.drafted += 1
    counts.approved += approved
    counts.sent += sent


def summarize_memory_usage(
    candidate_id: str,
    *,
    batches: Sequence[OutreachBatch],
    approvals: Mapping[str, OutreachApproval],
    audits: Sequence[OutreachAudit],
) -> MemoryUsageReport:
    sent = {
        (audit.batch_id, audit.number, audit.item_digest)
        for audit in audits
        if audit.result is OutreachResult.SENT
    }
    versions: dict[tuple[str | None, str | None], MemoryVersionUsage] = {}
    rules: dict[tuple[str, str], PreferenceRuleUsage] = {}
    report = MemoryUsageReport(candidate_id=candidate_id)
    for batch in batches:
        approval = approvals.get(batch.batch_id)
        approved_numbers = (
            set(approval.approved_numbers)
            if approval is not None and approval.batch_digest == batch.batch_digest
            else set()
        )
        for item in batch.items:
            binding = item.source_binding
            if binding is not None and binding.candidate_id != candidate_id:
                continue
            flags = {
                "approved": item.number in approved_numbers,
                "sent": (batch.batch_id, item.number, item.item_digest) in sent,
            }
            generation = binding.generation if binding is not None else None
            if generation is None:
                _bump(report.unattributed, **flags)
                continue
            key = (generation.memory_version, generation.dynamic_rules_version)
            version = versions.setdefault(key, MemoryVersionUsage(
                memory_version=key[0], dynamic_rules_version=key[1],
            ))
            _bump(version, **flags)
            if generation.memory_version is None:
                continue
            for rule_id in generation.preference_rule_ids:
                rule = rules.setdefault((generation.memory_version, rule_id), PreferenceRuleUsage(
                    rule_id=rule_id, memory_version=generation.memory_version,
                ))
                _bump(rule, **flags)
    report.memory_versions = sorted(
        versions.values(), key=lambda v: (v.memory_version or "", v.dynamic_rules_version or "")
    )
    report.rules = sorted(rules.values(), key=lambda r: (r.memory_version, r.rule_id))
    return report
