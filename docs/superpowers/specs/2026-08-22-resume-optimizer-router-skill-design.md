# Pluggable Resume Optimizer Router and Atomic Skill Design

**Status:** Approved
**Date:** 2026-08-22
**Supersedes:** `2026-08-21-resume-optimizer-design.md`
**Scope:** master-resume reconstruction, JD-specific tailoring, repository capability indexing, atomic Skill routing, evidence confirmation, verification, diffing, and resumable optimization sessions
**Out of scope:** candidate fact invention, application approval, connector delivery, CAPTCHA handling, and automatic submission

## 1. Objective

Build a reusable Resume Optimizer that can:

1. reconstruct a strong master resume from multiple resume sources and user feedback;
2. tailor a confirmed master resume to a target JD;
3. use existing repository capabilities through a functional index instead of duplicating them;
4. load only the Skill, policy, prompt, and context needed for the current intent;
5. accept new Lens, Strategy, Prompt, and Verifier plugins without opening the mutation boundary;
6. generate a draft rewrite before factual confirmation, then ask one precise confirmation question below the output;
7. promote only confirmed evidence-backed claims into a final resume variant;
8. continue autonomous atomic-Skill routing until it converges, pauses for a human, reaches budget, or detects a conflict.

The optimizer remains evidence-grounded. Fluency, ATS coverage, recruiter appeal, and keyword matching cannot authorize unsupported claims.

## 2. Decisions

The approved design decisions are:

- Use a product Router plus an internal Optimizer Router and nested atomic Skill packs.
- Keep `skills/job-hunting/SKILL.md` as the only globally discovered product Skill.
- Index selected existing repository capabilities and load them on demand.
- Consume Phase 3 Job Intelligence artifacts instead of reimplementing JD decomposition and evidence matching.
- Allow plugins to add Lens, Strategy, Prompt, and Verifier capabilities.
- Keep rewrite mutations closed to `paraphrase`, `compress`, `emphasize`, `reorder`, `translate`, `combine`, and `omit`.
- Allow `DraftEvidence` to drive a visible draft rewrite.
- Put one combined confirmation question below each rewrite block, covering at most three atomic factual claims.
- Require confirmed canonical Evidence before a claim enters a final `ResumeVariant`.
- Use an autonomous Skill loop with an independent multi-signal termination controller.
- Keep deterministic validation, diff coverage, and evidence gates outside LLM authority.

## 3. Existing Repository Capabilities to Reuse

### 3.1 Shared contracts and capability ports

Reuse:

- `ContractModel` for strict versioned public contracts;
- `Capability[Input, Output]` for atomic Python-callable capabilities;
- `ReasoningProvider` for provider-neutral structured generation;
- typed `JobAgentError` subclasses for stable failures;
- content and policy digests for audit, cache identity, and checkpoint validity.

Each atomic runtime capability remains independently callable and has no hidden neighboring operation.

### 3.2 Candidate Core

Reuse Candidate Core as the authority for:

- resume parsing;
- gap detection;
- adaptive question records;
- draft Evidence creation;
- user edits;
- Evidence confirmation;
- canonical Candidate Profile and Evidence persistence.

`CandidateEvidenceService.confirm()` remains the only operation that promotes candidate Evidence to confirmed canonical status. The Optimizer may propose, display, revise, and route Evidence candidates, but cannot mark them confirmed by itself.

### 3.3 Job Intelligence

Consume these existing artifacts:

- `NormalizedJob`;
- `JobRequirementProfile`;
- `RequirementMatchSet`;
- `MatchResult`;
- evidence, requirement, and policy digests.

The Optimizer does not own JD decomposition, hard filtering, general candidate-job matching, or job ranking. If required artifacts are absent or stale, it invokes the indexed Job Intelligence capability through a port.

### 3.4 Optimizer baseline contracts

Retain and extend:

- `RewriteOperation`;
- `ResumeOptimizationPlan`;
- `ClaimLedger`;
- `VerificationReport`;
- `KeywordCoverageReport`;
- `ResumeDiff`;
- `ResumeVariant`;
- `ResumeCompatibilityResult`.

The old prompt-pack categories remain useful, but their responsibilities move behind indexed atomic Skills.

## 4. Product Modes

### 4.1 Master Resume Reconstruction

Inputs may include multiple resumes, profile records, interview answers, user corrections, positioning feedback, and style preferences.

The mode:

1. identifies duplicate or conflicting resume items;
2. builds stable source-item identities;
3. detects weak descriptions and missing Evidence;
4. asks targeted enrichment questions;
5. tests positioning and information hierarchy;
6. rewrites sections from available Evidence;
7. confirms newly introduced facts;
8. assembles a confirmed master resume.

The master resume represents the candidate's strongest supported reusable narrative. It is not tied to a single JD.

### 4.2 JD-specific Tailoring

Inputs include a confirmed master resume plus Job Intelligence artifacts.

The mode:

1. consumes requirement-to-Evidence mappings;
2. selects relevant supported material;
3. changes emphasis, ordering, compression, terminology, and faithful keywords;
4. verifies every changed claim;
5. produces a constrained diff and compatibility assessment.

Identity, employer, title, date, credential, ownership, and metric semantics remain protected.

## 5. Architecture

```text
skills/job-hunting/SKILL.md
  -> internal Optimizer Router
     -> Capability Index
        -> selected repository capability / policy / prompt pack / Lens
     -> Context Loader
     -> Atomic Skill Executor
     -> Verifier Layer
     -> Diff and Interaction Renderer
     -> Termination Controller
     -> Optimization Session Repository
```

The LLM proposes intent and capability selection. Deterministic components enforce registry membership, schemas, permissions, preconditions, Evidence boundaries, mutation operations, immutable fields, and termination.

## 6. Skill and Index Layout

```text
skills/job-hunting/
├── SKILL.md
├── optimizer/
│   ├── SKILL.md
│   ├── index/
│   │   ├── repository.yaml
│   │   ├── policies.yaml
│   │   └── builtin-lenses.yaml
│   ├── shared/
│   │   ├── evidence-policy.md
│   │   ├── context-policy.md
│   │   ├── routing-policy.md
│   │   ├── plugin-policy.md
│   │   └── output-contract.md
│   ├── atoms/
│   │   ├── analyze-*/
│   │   ├── enrich-*/
│   │   ├── strategy-*/
│   │   ├── rewrite-*/
│   │   ├── verify-*/
│   │   └── interaction-*/
│   └── plugins/
│       └── */plugin.yaml
└── references/optimizer/
    ├── workflow.md
    ├── evidence-contract.md
    ├── prompt-routing.md
    ├── quality-gates.md
    └── failure-handling.md
```

Each new atomic Skill folder contains:

```text
atom-name/
├── SKILL.md
├── capability.yaml
└── references/       # only when conditional detail is needed
```

`SKILL.md` frontmatter is authoritative for the atomic Skill name and routing description. `capability.yaml` supplies typed runtime metadata without duplicating the description. The registry loader compiles normalized entries into a `CapabilityRegistrySnapshot` with a stable digest.

The snapshot is generated from repository index files, atomic Skill metadata, and validated plugin manifests. It is not a second hand-maintained catalog. The active snapshot is persisted with the optimization session so a resumed run can detect registry drift.

## 7. Functional Capability Index

### 7.1 Purpose

The functional index provides a cheap first layer for routing. It explains what a repository capability does, when it applies, what it consumes, what it produces, and what permissions it requires.

The index does not load implementation details, full policy text, Skill bodies, resume documents, or prompt examples. Those are pulled only after selection.

### 7.2 Indexed resource kinds

```text
capability   typed executable operation
policy       non-executable invariant or decision policy
prompt-pack  runtime prompt resource bound to a typed capability
lens         optional analysis perspective producing PerspectiveFinding
```

Repository application approval, connector delivery, submission, and CAPTCHA-related operations are excluded from the Optimizer index.

### 7.3 CapabilityIndexEntry

```yaml
id: repo.candidate.detect-gaps
version: 1.0.0
kind: capability
description: >
  Detect missing or weak candidate knowledge for a target role. Use when a
  rewrite lacks factual support or needs enrichment. Output CandidateGap
  records only; do not create or confirm evidence.
entrypoint: jobagent.candidate.gaps:GapDetector
input_schema: CandidateGapDetectionInput
output_schema: CandidateGapSet
intents:
  - detect_evidence_gap
  - prepare_enrichment_question
required_context:
  - candidate_profile
  - evidence_summary
permissions:
  read:
    - candidate_profile
    - candidate_evidence
  write: []
preconditions: []
produces:
  - CandidateGap
verifiers: []
failure_policy:
  retry: never
  fallback: return_typed_failure
trust: core
```

Required fields are:

- stable namespaced ID and semantic version;
- discriminating description;
- resource kind and entrypoint;
- typed input and output schemas;
- observable intents;
- minimum required context;
- read and write permissions;
- preconditions and dependencies;
- produced artifact types;
- mandatory verifiers;
- failure policy and trust level.

### 7.4 Description standard

Descriptions use:

```text
capability outcome + observable trigger + exclusion boundary + output type
```

Descriptions must not contain implementation steps, broad catch-all language, hidden permissions, or claims that neighboring operations are included.

Bad:

```text
Improve resumes using AI.
```

Good:

```text
Detect unsupported facts, missing metrics, and ambiguous ownership in a resume
item. Use before or after rewriting when evidence completeness is uncertain.
Output EvidenceGap findings only; do not invent facts or edit text.
```

### 7.5 Initial repository index

The first index exposes selected existing capabilities:

| ID | Kind | Function | Mutation boundary |
|---|---|---|---|
| `repo.candidate.parse-resume` | capability | Parse a local resume into typed pages and warnings | read-only source artifact |
| `repo.candidate.detect-gaps` | capability | Detect missing, weak, or unconfirmed candidate knowledge | findings only |
| `repo.candidate.ask-question` | capability | Select a high-value candidate gap and compose a question | question/event only |
| `repo.candidate.add-draft-evidence` | capability | Persist unconfirmed Evidence from a user answer | draft only |
| `repo.candidate.confirm-evidence` | capability | Promote eligible Evidence after explicit user confirmation | human-guarded canonical mutation |
| `repo.jobs.extract-requirements` | capability | Produce atomic JD requirements with exact source spans | read-only reasoning artifact |
| `repo.jobs.match-evidence` | capability | Map requirements to admissible candidate Evidence | mappings only |
| `repo.jobs.refresh-intelligence` | capability | Recompute stale Job Intelligence artifacts | read-only job workflow |
| `repo.optimizer.contracts` | policy | Expose Rewrite, Claim, Verification, Diff, and Compatibility contracts | non-executable |
| `policy.optimizer.workflow` | policy | Define optimizer stage responsibilities and domain boundary | non-executable |
| `policy.optimizer.evidence` | policy | Define claim provenance and supported transformations | non-executable |
| `policy.optimizer.prompt-routing` | policy | Define minimum prompt context and untrusted-input handling | non-executable |
| `policy.optimizer.quality-gates` | policy | Define hard final-variant gates | non-executable |
| `policy.optimizer.failure-handling` | policy | Define typed failure and retry rules | non-executable |

Existing repository capabilities are wrapped by adapters where their current callable signatures do not directly satisfy the generic `Capability` protocol. The adapters do not duplicate domain logic.

`repo.candidate.ask-question` retains Candidate Core's single-gap question behavior. `enrich.ask-evidence` is an Optimizer interaction capability: it may use Candidate Core's gap ranking, groups at most three closely related factual gaps, and renders the single combined confirmation question required by this design.

## 8. Progressive Loading

The Router uses five context layers:

```text
L0  index IDs, descriptions, kinds, trust, and preconditions
L1  selected SKILL.md or repository adapter contract
L2  only required shared policies and plugin resources
L3  minimum JD spans, Evidence records, resume items, and user feedback
S   structured OptimizationSessionState and artifact digests
```

Rules:

- only eligible L0 entries are sent to the routing model;
- L1 is loaded only for selected entries;
- L2 policy references are deduplicated and ordered deterministically;
- L3 includes stable IDs and the smallest relevant data slice;
- confirmed Evidence referenced by an active claim cannot be removed by context budgeting;
- full transcripts are compacted into structured state rather than repeatedly appended;
- raw private resume bodies and provider payloads do not enter default logs.

## 9. Atomic Skill Catalog

### 9.1 Analyze and Lens

- `analyze.hr-scan`
- `analyze.positioning-gap`
- `analyze.jd-evidence-gap`
- `analyze.transferability`
- `analyze.recruiter-risk`

Bundled optional lenses:

- `lens.ai-agent-product`
- `lens.expert-capability-modeling`
- `lens.startup-product-lead`
- `lens.bigtech-product`
- `lens.technical-depth`

`lens.expert-capability-modeling` analyzes the narrative:

```text
identify expert judgment
-> decompose information filters, analytical frames, decision rules,
   exceptions, and quality standards
-> represent them as Agent, Tool, Skill, and Benchmark capabilities
-> demonstrate reuse across supported scenarios
```

It is optional and cannot universalize one candidate's example into a general resume rule.

### 9.2 Enrichment

- `enrich.detect-gap`
- `enrich.ask-evidence`
- `enrich.resolve-conflict`

### 9.3 Strategy

- `strategy.positioning`
- `strategy.information-hierarchy`
- `strategy.select-experience`
- `strategy.jd-tailoring`
- `strategy.cross-domain-narrative`

### 9.4 Rewrite

- `rewrite.summary`
- `rewrite.experience`
- `rewrite.project`
- `rewrite.skills`
- `rewrite.fuse-sources`
- `rewrite.compress`
- `rewrite.translate`
- `rewrite.jd-keywords`

### 9.5 Verification

- `verify.claim`
- `verify.metric`
- `verify.ownership`
- `verify.timeline-identity`
- `verify.diff`
- `verify.resume-quality`

### 9.6 Interaction

- `interaction.present-proposal`
- `interaction.confirm-evidence`

## 10. Router and Autonomous Skill Loop

### 10.1 UserInputEvent

The Router classifies continuous user input as one or more of:

```text
new_fact
factual_correction
new_metric
timeline_correction
ownership_correction
positioning_feedback
wording_critique
style_preference
target_role_change
scope_constraint
accept_proposal
reject_proposal
continue
stop
```

### 10.2 Candidate selection

For each event:

1. deterministic filtering removes entries with incompatible kind, schema, trust, permissions, dependencies, or preconditions;
2. the routing model receives eligible `id + description` entries;
3. it produces a typed `RoutingDecision`;
4. the Policy Engine validates the decision;
5. the Context Loader pulls only selected resources;
6. the executor runs the selected atomic capability;
7. outputs become new artifacts and routing events;
8. the loop continues until the Termination Controller changes state.

### 10.3 RoutingDecision

```text
intents
selected_capability_ids
affected_item_ids
required_context
confidence
expected_artifacts
reasoning_summary
continue_after_execution
```

The routing model cannot register capabilities, change permissions, expand mutation operations, confirm Evidence, or declare final verification passed.

### 10.4 Dynamic graph example

```text
positioning_feedback
-> analyze.positioning-gap
-> lens.expert-capability-modeling
-> strategy.positioning
-> rewrite.summary
-> verify.claim
-> enrich.ask-evidence
-> WAITING_FOR_HUMAN
```

After a correction:

```text
factual_correction
-> enrich.resolve-conflict
-> rewrite.summary
-> verify.claim
-> verify.diff
-> CONVERGED
```

The graph is not a fixed 3-6 step pipeline. The controller may continue selecting capabilities while meaningful findings remain.

## 11. Optimization Session State

```text
OptimizationSessionState
├── session_id
├── mode
├── candidate_id
├── target_job_id?
├── base_resume_ids[]
├── confirmed_facts[]
├── draft_evidence[]
├── evidence_conflicts[]
├── active_positioning
├── accepted_lenses[]
├── user_preferences[]
├── rejected_wordings[]
├── unresolved_questions[]
├── generated_artifacts[]
├── artifact_digests{}
├── capability_trace[]
├── loop_state
└── checkpoint_version
```

Transcript compaction updates this structure. The raw transcript is not treated as the source of truth for facts or accepted decisions.

## 12. Evidence Proposal and Confirmation

Canonical `EvidenceItem.user_confirmed` remains compatible with Candidate Core and Job Intelligence.

The Optimizer adds a separate session-level proposal:

```text
OptimizationEvidenceProposal
├── proposal_id
├── status: DRAFT | CORRECTED | REJECTED | UNCERTAIN
├── statement
├── metric_facts[]
├── source_event_id
├── affected_item_ids[]
├── affected_claim_ids[]
├── supersedes_proposal_id?
└── canonical_evidence_id?
```

Flow:

```text
user input
-> OptimizationEvidenceProposal(DRAFT)
-> visible RewriteProposal
-> one combined confirmation question
-> user confirms / corrects / rejects / marks uncertain
-> Candidate Core draft or edit
-> explicit Candidate Core confirmation
-> canonical EVID_* reference
-> final verification
```

Draft proposals may support exploration output. They cannot support the final `ResumeVariant`.

Each rewrite block contains at most three unconfirmed atomic facts. The output ends with one precise question covering truth, metric, chronology, scope, or ownership. Style preferences and wording critiques take effect directly and do not require Evidence confirmation.

## 13. Rewrite Contract

Allowed operations remain:

```text
paraphrase
compress
emphasize
reorder
translate
combine
omit
```

Every rewrite returns:

```text
RewriteProposal
├── proposal_id
├── before
├── after
├── operations[]
├── evidence_refs[]
├── evidence_proposal_refs[]
├── requirement_ids[]
├── affected_item_ids[]
├── unresolved_claims[]
├── rationale
└── risk_notes[]
```

Plugins may influence strategy or prompt selection but cannot add a new operation or directly mutate a final resume.

## 14. Plugin Model

### 14.1 Open extension points

Third-party and project-local plugins may register:

- Lens;
- Strategy;
- Prompt;
- Verifier.

They produce controlled typed artifacts such as `PerspectiveFinding`, `StrategyProposal`, `RewriteProposal`, or `VerificationFinding`.

### 14.2 Closed boundaries

Plugins cannot:

- add `RewriteOperation` values;
- change Candidate Core Evidence confirmation;
- bypass required Verifiers;
- edit immutable identity fields;
- widen Evidence scope;
- modify registry permissions at runtime;
- trigger application approval or delivery;
- invoke connectors from the Optimizer loop;
- weaken retry or failure rules.

### 14.3 Plugin manifest

```yaml
id: acme.lens.ai-product-leadership
version: 1.2.0
api_version: 1.0
entrypoint: lens/SKILL.md
components:
  - kind: lens
    capability: lens.ai-product-leadership
    metadata: lens/capability.yaml
requires:
  optimizer_api: ">=1.0,<2.0"
permissions:
  read:
    - resume_item
    - evidence_summary
    - target_role
  write:
    - perspective_finding
trust: third_party
```

The loader rejects duplicate IDs, incompatible API versions, undeclared schemas, forbidden permissions, path escapes, missing entrypoints, and attempts to register closed mutation operations.

## 15. Verification and Final Promotion

Each substantive final claim must:

- cite one or more canonical confirmed `EVID_*` IDs;
- preserve metric value, unit, population, direction, and time window;
- preserve ownership, scope, chronology, title, employer, and credential semantics;
- map to a base resume item or confirmed candidate Evidence;
- appear in the diff when changed;
- pass model-based entailment followed by deterministic checks.

Hard gates remain:

```text
unsupported claims = 0
unsupported metrics = 0
contradicted claims = 0
semantic exaggerations = 0
evidence coverage = 100% of substantive final claims
diff coverage = 100% of changed substantive claims
schema validity = 100%
```

## 16. Termination Controller

The loop states are:

```text
RUNNING
WAITING_FOR_HUMAN
CONVERGED
BUDGET_PAUSED
BLOCKED_CONFLICT
FAILED
```

The controller ends or pauses execution when:

- all required hard Verifiers pass and no material finding remains;
- two consecutive iterations produce no material improvement;
- Evidence confirmation is required;
- an unresolved contradiction affects the active rewrite;
- verifier findings oscillate;
- the same capability repeats without a meaningful diff;
- configured cost, token, call, or time budget is reached;
- the user stops the run;
- a non-recoverable contract or plugin failure occurs.

Every pause persists a checkpoint. Resumption validates registry, prompt, Evidence, requirement, policy, and base-resume digests before continuing.

## 17. Failure Handling

Extend typed failures with:

```text
CAPABILITY_NOT_REGISTERED
CAPABILITY_PRECONDITION_FAILED
PLUGIN_MANIFEST_INVALID
PLUGIN_PERMISSION_DENIED
PLUGIN_INCOMPATIBLE
ROUTING_DECISION_INVALID
ROUTING_LOW_CONFIDENCE
LOOP_OSCILLATION
LOOP_BUDGET_EXCEEDED
CHECKPOINT_STALE
EVIDENCE_CONFIRMATION_REQUIRED
IMMUTABLE_FIELD_CHANGE
```

Rules:

- structured provider output receives at most one format-repair attempt;
- transient provider transport retry remains bounded;
- Evidence, permission, immutable-field, and policy failures are never retried with weaker instructions;
- a failing plugin is quarantined without disabling compatible core capabilities;
- conflicting Evidence is preserved as an explicit conflict set;
- raw private content is excluded from default exception messages and logs.

## 18. Prompt Resources

Runtime prompt packs remain package resources under `src/jobagent/optimizer/promptpacks/`. They are bound to indexed capabilities rather than loaded as one large optimizer prompt.

The old pack maps as follows:

| Old pack | New owner |
|---|---|
| `jd/*` | Job Intelligence capability index |
| `evidence/*` | analyze and enrich Skills |
| `strategy/*` | strategy Skills |
| `rewrite/*` | rewrite Skills |
| `coverage/*` | recruiter analysis and resume-quality verification |
| `verify/*` | verify Skills |
| `explain/*` | interaction Skills |
| `compatibility/*` | compatibility capability |

Prompt depth comes from specialization, measured evaluation benefit, and progressive disclosure. Repeated general instructions and unmeasured examples are excluded.

## 19. Persistence and Audit

Persist:

- optimization sessions and checkpoints;
- registry snapshot digest;
- selected capability IDs and versions;
- prompt bundle digest;
- source and target artifact digests;
- Evidence proposal transitions;
- human confirmations and corrections;
- rewrite proposals and diffs;
- verifier findings;
- termination decisions;
- provider timing, token, and cost metadata when available.

Default logs exclude full resume content, contact details, raw prompts, raw provider payloads, and private Evidence bodies.

## 20. Testing

### 20.1 Index and plugin tests

- valid repository and atomic Skill entries compile into one registry snapshot;
- duplicate IDs and incompatible versions fail;
- descriptions are present and discriminating;
- referenced entrypoints, schemas, and Skill files exist;
- forbidden plugin permissions and mutation operations fail;
- registry ordering and digest are deterministic.

### 20.2 Router tests

- continuous user inputs produce typed event classifications;
- deterministic eligibility filtering happens before semantic ranking;
- selected IDs are registered and permission-compatible;
- low confidence does not authorize mutation;
- new findings may trigger another atomic capability;
- stop, pause, resume, and stale-checkpoint behavior is deterministic.

### 20.3 Evidence tests

- new user facts can produce a draft rewrite;
- final variants reject proposal-only Evidence;
- one confirmation question contains no more than three atomic facts;
- confirmation promotes through Candidate Core;
- correction creates a revision link and retracts stale derived text;
- rejection removes derived claims;
- uncertain facts remain exploration-only;
- conflicts cannot be silently overwritten.

### 20.4 Rewrite and verification tests

- only the seven operations are accepted;
- identity and timeline fields are immutable without explicit correction;
- no RAG Evidence prevents a RAG implementation claim;
- conceptual knowledge does not become production experience;
- participation does not become leadership;
- metrics preserve value, unit, population, direction, and time window;
- compatible Evidence can be combined without broadening meaning;
- unsupported JD keywords are reported instead of inserted;
- every changed substantive claim appears in the diff.

### 20.5 Adversarial tests

- instructions embedded in JD, resume, Evidence, user attachments, or plugin text cannot change policy;
- plugins cannot request tools, connectors, approval, or delivery;
- malformed structured output cannot bypass deterministic validation;
- recursive routing, repeated no-op rewrites, and verifier oscillation pause safely.

### 20.6 Real-use-case regression

Use the two-resume AI Agent product-manager reconstruction case to verify:

- multi-source fusion;
- iterative evidence enrichment;
- timeline correction;
- metric confirmation;
- positioning changes from domain-specific AI toward expert capability modeling;
- Agent, Tool, Skill, and Benchmark terminology remains evidence-grounded;
- cross-domain reuse is expressed only for supported scenarios;
- user wording rejection causes a routed rewrite without losing confirmed facts.

Tests assert behavioral invariants and artifact contracts rather than exact generated prose.

## 21. Implementation Slices

1. Extend schemas for index entries, routing, session state, Evidence proposals, rewrite proposals, findings, and termination.
2. Build repository capability adapters and functional index loader.
3. Build registry compilation, validation, permissions, versioning, and digesting.
4. Create internal Optimizer Router Skill, shared policies, and atomic Skill skeletons with validated descriptions.
5. Build event classification, routing decision validation, and progressive Context Loader.
6. Implement resumable Optimization Session Repository and Termination Controller.
7. Implement master-resume source fusion, analysis, enrichment, positioning, and interaction capabilities.
8. Implement JD-tailoring capabilities consuming Job Intelligence artifacts.
9. Implement rewrite atoms, Claim Ledger extraction, deterministic Verifiers, Diff, and final promotion.
10. Add plugin loading, quarantine, and compatibility validation.
11. Add CLI or service workflow entrypoints, golden evaluations, and the real-use-case regression.

Each slice is independently testable. No slice adds application approval or connector delivery behavior.

## 22. Acceptance Criteria

The design is complete when implementation proves:

- selected existing repository capabilities are discoverable through functional descriptions;
- only selected Skill bodies and context are loaded;
- plugins can add permitted capability kinds without changing core mutation operations;
- user facts can drive a draft rewrite followed by one confirmation question;
- final claims use canonical confirmed Evidence only;
- the Router can dynamically continue across atomic Skills;
- the Termination Controller prevents unbounded or oscillating execution;
- every final changed claim is evidence-backed, verified, and represented in the diff;
- resume optimization remains isolated from approval and delivery.
