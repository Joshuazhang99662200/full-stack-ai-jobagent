# Evidence-grounded Resume Optimizer Design

**Status:** Approved design baseline  
**Date:** 2026-08-21  
**Scope:** JD-to-CV optimization, verification, explanation, and compatibility  
**Out of scope:** candidate fact creation, human evidence confirmation, application approval, and delivery

## 1. Objective

The optimizer produces a job-targeted resume variant using only candidate facts supported by admissible evidence. It improves relevance, ordering, phrasing, concision, language, and keyword coverage while preserving ownership, scope, chronology, metrics, and confidence.

Deep optimization is implemented as a sequence of small prompt-backed capabilities with typed contracts and deterministic gates. It is not a single prompt that consumes a JD and emits a complete resume.

## 2. Selected Approach

Three approaches were considered:

1. A monolithic rewrite prompt is simple but cannot isolate failures, reliably enforce claim provenance, or support focused evaluations.
2. A staged prompt pipeline provides typed intermediate artifacts, evidence traceability, replaceable stages, and targeted evaluation. This is the selected approach.
3. A multi-agent debate system may increase quality in some workloads but introduces cost, latency, and state complexity without evidence that the first release needs it.

The first release supports an independently configured verifier model, but generation and verification remain ordinary sequential application services rather than autonomous agents.

## 3. Inputs and Outputs

Required inputs:

- `BaseResumeDocument`
- `CandidateProfile`
- admissible `EvidenceItem` records
- `NormalizedJob`
- `JobRequirementProfile`
- `OptimizationPolicy`
- target language and locale
- target rendering template constraints

Primary outputs:

- `ResumeOptimizationPlan`
- `ResumeVariant`
- `ClaimLedger`
- `KeywordCoverageReport`
- `ResumeDiff`
- `VerificationReport`
- `ResumeCompatibilityResult`

All outputs carry schema versions, source artifact IDs, generation timestamp, prompt bundle digest, provider execution metadata, and deterministic content digests.

## 4. Pipeline

```text
1. Requirement decomposition
2. Requirement priority and risk analysis
3. Evidence retrieval
4. Evidence-to-requirement ranking
5. Positioning strategy
6. Section-level optimization plan
7. Constrained drafting
8. Claim extraction
9. Evidence entailment verification
10. Metric and semantic-exaggeration verification
11. Keyword and ATS audit
12. Resume diff and explanation
13. Renderable variant assembly
14. Resume-to-job compatibility assessment
```

Every stage validates its output before the next stage begins. Invalid structured output receives at most one schema-repair attempt. A second failure returns a typed provider-output error.

## 5. Requirement Decomposition

The decomposer transforms a normalized JD into atomic `RequirementItem` records:

```text
id
category
statement
priority
requiredness
seniority_signal
ownership_signal
metric_signal
keywords
source_span
confidence
```

Requiredness is one of `MUST`, `PREFERRED`, `CONTEXT`, or `UNCERTAIN`. The decomposer preserves the source span so later explanations can cite the exact JD text that motivated an optimization.

Risk analysis identifies ambiguous seniority, inflated title expectations, impossible constraints, conflicting requirements, discriminatory language, suspicious compensation, and requirements that must be handled by the deterministic hard filter rather than resume rewriting.

## 6. Evidence Retrieval and Ranking

Evidence retrieval uses deterministic filters first:

- confirmation and confidence policy;
- time range and chronology;
- skill and domain tags;
- experience, project, achievement, management, or commercial type;
- target language availability;
- explicit exclusions.

A provider-neutral semantic retriever may add candidates but cannot change evidence admissibility. The reranker maps each requirement to zero or more evidence records and produces relevance, strength, recency, specificity, and contradiction signals.

If an important requirement has no admissible evidence, the result contains `MISSING_EVIDENCE`; no drafting stage may create a claim for it.

## 7. Positioning Strategy

The strategy stage chooses how to present the supported candidate facts for this job. It decides:

- which supported strengths lead the summary;
- which experience bullets receive prominence;
- which weak or irrelevant material is compressed or omitted;
- which exact keywords can be used without changing meaning;
- whether a gap should be disclosed as a gap, omitted, or returned to adaptive interview;
- the target language and terminology conventions.

The strategy never edits the evidence graph. It produces a plan that the drafting stages must follow.

## 8. Runtime Prompt Pack

```text
src/jobagent/optimizer/promptpacks/
├── manifest.yaml
├── shared/
│   ├── evidence-policy.md
│   ├── untrusted-input-policy.md
│   ├── language-policy.md
│   └── output-discipline.md
├── jd/
│   ├── decompose.md
│   └── risk-signals.md
├── evidence/
│   ├── query-expansion.md
│   ├── relevance-rerank.md
│   └── conflict-resolution.md
├── strategy/
│   ├── positioning.md
│   └── section-plan.md
├── rewrite/
│   ├── professional-summary.md
│   ├── experience-bullets.md
│   ├── projects.md
│   ├── skills.md
│   └── education.md
├── coverage/
│   ├── keywords.md
│   └── ats-readability.md
├── verify/
│   ├── claim-entailment.md
│   ├── metric-fidelity.md
│   ├── semantic-exaggeration.md
│   └── contradiction-check.md
├── explain/
│   └── resume-diff.md
└── compatibility/
    └── variant-job-fit.md
```

Prompt depth comes from specialization and evaluation rather than repeated instructions. Shared policies are selected and assembled once for a stage. Examples remain only when they encode a product requirement or fix a measured evaluation failure.

## 9. Prompt Manifest

Every prompt entry has:

```yaml
id: rewrite.experience_bullets
version: 1.0.0
stage: drafting
input_schema: ExperienceRewriteInput
output_schema: ExperienceRewriteResult
required_context:
  - selected_evidence
  - target_requirements
  - original_section
safety_rules:
  - no_new_claim
  - preserve_metric_semantics
  - evidence_id_required
model_capabilities:
  - structured_output
max_repair_attempts: 1
```

The complete prompt bundle has a stable digest derived from manifest content and referenced prompt files. Every generated variant stores that digest.

`PromptAssembler` performs deterministic routing and ordering:

1. applicable shared policy;
2. stage task instruction;
3. exact output schema;
4. minimum relevant JD spans;
5. minimum admissible evidence records;
6. original resume section;
7. evaluated examples when the prompt declares them.

Context budgeting removes low-ranked unused evidence first. It may not remove evidence referenced by the stage plan or a generated claim.

## 10. Skill Context Boundary

Agent-facing optimizer guidance lives under:

```text
skills/job-hunting/references/optimizer/
├── workflow.md
├── evidence-contract.md
├── prompt-routing.md
├── quality-gates.md
└── failure-handling.md
```

These references tell an external coding agent when and how to invoke optimizer capabilities, interpret failures, route missing evidence to interview, and present diffs for human review.

Runtime prompts are package resources used by `PromptAssembler`. Skill references do not duplicate runtime prompt text. Both layers share the same public schemas and architectural invariants.

## 11. Constrained Drafting

Drafting operates section by section. Each generated substantive bullet returns:

```text
text
evidence_ids
requirement_ids
source_resume_item_ids
rewrite_operations
confidence
```

Allowed operations are reordering, compression, paraphrase, translation, emphasis, combination of compatible evidence, and omission.

Disallowed operations include:

- adding an unsupported responsibility;
- increasing ownership or decision authority;
- changing participation into leadership;
- creating a metric or changing a metric's value, unit, population, or direction;
- implying production experience from conceptual knowledge;
- combining evidence in a way that creates a broader claim than any evidence supports;
- changing dates, employers, titles, credentials, or education facts without explicit evidence.

## 12. Claim Ledger

After drafting, the system extracts every substantive claim into `ClaimRecord`:

```text
claim_id
resume_item_id
text
claim_type
evidence_ids
requirement_ids
metric_facts
ownership_level
verification_status
verification_reasons
```

Substantive claims include experience, skill application, achievements, metrics, ownership, team scope, commercial impact, credentials, dates, and domain experience. Pure formatting and connective language do not require evidence records.

## 13. Verification

The verifier evaluates each claim against only the cited evidence and returns:

```text
SUPPORTED
PARTIALLY_SUPPORTED
UNSUPPORTED
CONTRADICTED
```

Hard failure conditions:

- one or more unsupported claims;
- one or more contradicted claims;
- a new or altered metric without explicit evidence;
- a substantive claim without evidence IDs;
- ownership, scope, seniority, or authority stronger than the evidence;
- a generated claim that cannot be mapped to the base resume or confirmed evidence graph.

Partially supported claims are excluded from the final variant unless a deterministic rewrite reduces them to the supported scope and the verifier then marks them supported.

The draft generator cannot override verification. A model-based verifier is followed by deterministic checks for IDs, metrics, dates, titles, employers, and required output coverage.

## 14. Keyword and ATS Audit

Keyword coverage distinguishes:

- directly supported exact keywords;
- supported synonyms;
- supported adjacent terminology;
- missing keywords with no evidence;
- prohibited keyword stuffing.

Only directly supported exact keywords and faithful synonyms may be added to the resume. Missing unsupported keywords appear in the report and may create candidate interview suggestions.

The ATS audit checks structure, section names, text extraction, bullet length, date consistency, contact-field presence policy, and template constraints. ATS scoring cannot authorize a factual rewrite.

## 15. Diff and Explanation

Every changed item produces:

```text
original
optimized
reason
requirement_ids
evidence_ids
rewrite_operations
risk_notes
```

The human reviewer can trace what changed, why it changed, which JD requirement motivated it, and which evidence supports it. Deleted content is also recorded with its omission reason.

## 16. Compatibility

Candidate-job match measures whether the person fits the job. Resume-job compatibility measures whether a specific resume variant presents the relevant supported evidence for that job.

Compatibility uses configurable thresholds:

```text
safe reuse
human review
tailor separately
```

Threshold values live in typed configuration and are never embedded in prompt text or business code. Compatibility never triggers delivery.

## 17. Missing Evidence Feedback Loop

When a high-priority requirement lacks evidence:

```text
MISSING_EVIDENCE
-> CandidateGap
-> adaptive interview question proposal
-> user answer
-> draft EvidenceItem
-> human confirmation
-> rerun optimizer
```

The optimizer may propose a question but cannot answer it, create evidence, or mark evidence confirmed.

## 18. Untrusted Input and Privacy

JD, resume, profile notes, and connector text are untrusted data. Instructions embedded in those inputs cannot change system policy, request tools, reveal prompts, approve an application, or trigger delivery.

Prompt assembly uses explicit data boundaries and stage-specific context. The model receives only fields required by the current stage.

Execution logs store prompt ID, prompt bundle digest, model configuration, timing, token counts when available, artifact IDs, and outcome. Full private resume content, contact information, and raw model payloads are excluded from default logs.

## 19. Failure Handling

Typed optimizer failures include:

- `MISSING_EVIDENCE`
- `EVIDENCE_CONFLICT`
- `INVALID_PROVIDER_OUTPUT`
- `UNSUPPORTED_CLAIM`
- `UNSUPPORTED_METRIC`
- `SEMANTIC_EXAGGERATION`
- `CONTRADICTED_CLAIM`
- `CONTEXT_LIMIT_EXCEEDED`
- `RENDER_VALIDATION_FAILED`
- `USER_REVIEW_REQUIRED`

Provider transport retries are bounded and apply only when the provider declares the failure transient. Schema repair happens once. Evidence and policy failures are not retried with looser prompts.

## 20. Evaluation Suite

Prompt changes run against a versioned golden dataset. Each case contains a candidate profile, evidence graph, base resume, JD, expected allowed transformations, and prohibited claims.

Required evaluation cases include:

- no RAG evidence prevents a RAG implementation claim;
- conceptual knowledge does not become production experience;
- “assisted” does not become “led”;
- a 30% metric does not become 50%;
- metric unit, population, direction, and time window remain intact;
- multiple compatible evidence items may be combined without broadening the claim;
- conflicting evidence blocks the affected claim;
- Chinese-English translation preserves ownership and metric meaning;
- unsupported keywords are reported instead of inserted;
- keyword stuffing is rejected;
- every substantive bullet has valid evidence IDs;
- every changed claim appears in the diff;
- the verifier can reject an otherwise fluent draft;
- compatibility recommends only variants above configured thresholds.

Hard quality gates:

```text
unsupported claims = 0
unsupported metrics = 0
contradicted claims = 0
semantic exaggerations = 0
evidence coverage = 100% of substantive claims
diff coverage = 100% of changed substantive claims
schema validity = 100%
```

Quality, latency, token usage, and provider cost are recorded separately. Lower cost or latency is considered an improvement only when all hard gates continue to pass.

## 21. Implementation Slices

The optimizer is delivered in independently testable slices:

1. Schemas, prompt manifest, loader, assembler, and fake reasoning provider.
2. Requirement decomposition and typed requirement profile integration.
3. Evidence retrieval, admissibility, ranking, and missing-evidence results.
4. Positioning and section-level optimization planning.
5. Section drafting and claim-ledger extraction.
6. Model-based entailment plus deterministic metric, date, title, and ownership verification.
7. Keyword coverage, ATS checks, and diff generation.
8. Resume variant persistence, rendering contract, and compatibility scoring.
9. Golden dataset, provider contract tests, and end-to-end optimizer workflow.

No slice introduces application approval or connector delivery behavior.
