---
name: job-hunting
description: Use for evidence-grounded candidate onboarding, job intelligence, JD-to-CV optimization, application review, approved delivery, auditing, or JobAgent connector work. Do not use for generic career advice that does not need the project workflow.
---

# Human-approved Job Hunting

Compose the project's atomic capabilities. Inspect outputs and preserve approval boundaries; do not recreate domain logic inside the skill.

## Hard rules

- Never send without a valid human approval bound to the current job, resume, message, and policy digests.
- Never invent candidate facts or silently promote weak or inferred evidence.
- Never silently promote a `REVIEW` job.
- Never bypass login, CAPTCHA, verification, risk control, rate limits, or platform changes.

## Context routing

- For the complete product contract, read [references/product-spec.md](references/product-spec.md).
- For cross-domain boundaries, read [references/architecture-invariants.md](references/architecture-invariants.md) and [references/capability-catalog.md](references/capability-catalog.md).
- For onboarding or interview work, read [references/candidate-kb.md](references/candidate-kb.md) and [references/evidence-policy.md](references/evidence-policy.md).
- For normalization, filtering, matching, or ranking, read [references/job-intelligence.md](references/job-intelligence.md).
- For resume work, read [references/resume-grounding.md](references/resume-grounding.md). For deep optimizer work, additionally read [references/optimizer/workflow.md](references/optimizer/workflow.md), [references/optimizer/evidence-contract.md](references/optimizer/evidence-contract.md), [references/optimizer/prompt-routing.md](references/optimizer/prompt-routing.md), [references/optimizer/quality-gates.md](references/optimizer/quality-gates.md), and [references/optimizer/failure-handling.md](references/optimizer/failure-handling.md).
- For preview, approval, send, batch, or audit, read [references/hitl-approval.md](references/hitl-approval.md).
- For connector development, read [references/connector-contract.md](references/connector-contract.md) and [references/oss/source-manifest.yaml](references/oss/source-manifest.yaml), then load only the named upstream note needed for the task.

## Workflow

Check candidate readiness before sourcing. Normalize and deduplicate jobs before deterministic filtering and explainable matching. For a strong match, optimize the resume from admissible evidence, verify every claim, generate a diff and message, and prepare a review package. Ask for human approval immediately before delivery. After delivery, offer compatibility-based batch review and record every attempt in audit.
