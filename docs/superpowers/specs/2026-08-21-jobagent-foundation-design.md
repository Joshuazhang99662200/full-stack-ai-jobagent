# Human-in-the-loop JobAgent Foundation Design

**Status:** Approved design baseline  
**Date:** 2026-08-21  
**Project license:** Apache-2.0  
**Runtime baseline:** Python 3.11+, Pydantic v2, Typer, SQLite, pytest

## 1. Product Contract

JobAgent is an evidence-grounded, human-approved AI job-hunting agent. It exposes small, composable capabilities that Codex, Claude Code, Cursor, a CLI, an MCP server, or ordinary Python code can call independently.

The product does not implement an automatic mass-application bot. Search, judgment, document generation, approval, and delivery remain separate operations. Every irreversible action requires a valid human approval bound to the exact reviewed artifacts.

The first complete workflow must run offline with a mock connector:

```text
resume source
-> candidate knowledge base
-> adaptive interview
-> confirmed evidence
-> mock job search
-> JD normalization
-> deterministic hard filter
-> evidence-based match
-> resume optimization
-> evidence verification
-> resume diff
-> application preview
-> human approval
-> mock send
-> resume compatibility cluster
-> batch approval
-> sequential batch send
-> audit
```

## 2. Architectural Invariants

These rules are domain contracts and must be represented in schemas, service boundaries, and tests:

```text
CandidateProfile != Resume
Evidence is the source of truth for candidate claims
JobSource != Job Intelligence
Candidate-Job Match != Resume-Job Compatibility
Resume Tailoring != Fact Generation
Preview != Approval
Approval != Send
Platform Connector != Domain Core
Search != Apply
Review != Auto Promote
CAPTCHA != Retry
```

Additional hard rules:

- No evidence means no new substantive claim.
- Unknown information is valid and must not be guessed.
- A REVIEW job cannot be silently promoted to PASS.
- A platform verification or risk-control response stops the affected workflow.
- Browser credentials, cookies, private resumes, contact details, and session tokens never enter Git.
- Batch delivery is sequential by default.

## 3. Architecture Style

The system uses a ports-and-adapters architecture with an explicit application layer:

```text
CLI / MCP / Agent Skill
          |
Application capabilities
          |
Domain models + domain services
          |
Repository and provider ports
          |
SQLite / LLM providers / platform connectors / renderers
```

Domain code imports no browser automation library, platform DOM selector, Chrome profile path, vendor SDK model, or application framework type. Connectors translate platform-specific behavior into stable domain results.

The first version uses ordinary Python orchestration. A graph framework may be introduced only after a concrete workflow requires durable graph-state behavior that cannot be expressed cleanly through application services.

## 4. Package Boundaries

```text
src/jobagent/
├── candidate/       Candidate profile, evidence, gaps, interview decisions
├── jobs/            Normalized jobs, requirements, dedupe, filters, matching
├── optimizer/       JD-to-CV planning, rewriting, verification, diff
├── applications/    Preview packages, approvals, send gates, batch workflow
├── audit/           Immutable application attempts and query services
├── connectors/      JobSource adapters; mock connector ships first
├── storage/         SQLite repositories and migrations
├── reasoning/       Provider-neutral structured reasoning port
├── rendering/       Resume rendering ports and local implementations
├── schemas/         Shared serialized contracts and schema versions
├── cli/             Typer command groups; no domain logic
└── config/          Typed local configuration and threshold policies
```

Each package owns its public interfaces. Cross-package communication uses typed domain objects rather than dictionaries with undocumented fields.

## 5. Atomic Capability Catalog

The public capability surface includes at least:

```text
candidate.parse_resume
candidate.detect_gaps
candidate.ask_question
candidate.update_profile
candidate.add_evidence

job.search
job.fetch
job.normalize
job.dedupe
job.hard_filter
job.match
job.rank

resume.retrieve_evidence
resume.plan
resume.tailor
resume.verify
resume.render
resume.diff

message.generate

application.prepare
application.preview
application.approve
application.send
application.audit

cluster.resume_compatibility
```

Every capability has a versioned input schema, a versioned output schema, declared dependencies, explicit errors, no hidden external side effects, and direct Python test coverage. Side-effecting capabilities are exposed separately from read-only and planning capabilities.

## 6. Candidate Knowledge Base

The candidate knowledge base is canonical. A resume is an input source and later a generated projection.

Logical local layout:

```text
candidate/
├── profile.json
├── evidence.json
├── preferences.json
├── constraints.json
├── search_strategy.json
└── private/
    └── source_resume.pdf
```

SQLite is the operational store; JSON export provides a portable, inspectable representation. Private source files remain outside version control.

Core domain types include:

- `CandidateProfile`
- `Experience`
- `Education`
- `Skill`
- `Project`
- `Achievement`
- `DomainExperience`
- `ManagementExperience`
- `CommercialExperience`
- `Language`
- `Certification`
- `Preference`
- `Constraint`
- `UnknownField`
- `EvidenceItem`

Every `EvidenceItem` has a stable ID, statement, type, related skills and domains, metric facts, time range, source reference, confidence, and confirmation state. Inferred or weak evidence cannot support a final substantive resume claim until policy permits it and the user has confirmed it.

## 7. Adaptive Interview

Interview questions are selected from current gaps rather than a fixed questionnaire. The selector considers:

- missing information;
- ambiguous ownership or scope;
- high-value weak evidence;
- relevance to current target roles;
- expected information gain;
- recent questions, to avoid repetition.

Each question should resolve one primary gap. The user can skip. A skipped or unanswered gap remains explicit. Interview answers create draft evidence first and require confirmation before being treated as established fact.

Candidate readiness reports profile completeness, high-value gaps, weak claims, confirmed evidence count, and target-role readiness. Completeness is descriptive rather than a requirement to invent missing data.

## 8. Job Domain and Connectors

`JobSource` is a provider-neutral protocol with separate operations:

```python
search(...)
fetch_job(...)
get_recruiter(...)
preview_application(...)
submit_application(...)
```

`MockJobSource` is implemented first and supports the full offline workflow. Real connectors live under isolated adapter packages and translate platform states into typed results.

The standardized stop states are:

```text
LOGIN_REQUIRED
CAPTCHA_REQUIRED
VERIFICATION_REQUIRED
RISK_CONTROL
PLATFORM_CHANGED
USER_INTERVENTION_REQUIRED
```

The application layer never converts these states into automatic bypass, stealth, unlimited retry, or keyword substitution behavior.

Normalized jobs retain source provenance. Cross-source deduplication may merge equivalent jobs but must preserve all observed source IDs and URLs.

## 9. Job Intelligence

JD normalization creates a `JobRequirementProfile` with must-have requirements, preferences, responsibilities, skills, domains, seniority, management scope, commercial scope, education, languages, location constraints, and risk signals.

Deterministic hard filtering runs before LLM-based matching. It returns `PASS`, `REVIEW`, or `REJECT`; every rejection includes a machine-readable rule ID and human-readable reason.

Matching returns dimension scores, positive evidence, partial matches, hard gaps, uncertainties, and evidence IDs. An overall score without an explanation is invalid.

## 10. Resume Optimizer Boundary

The optimizer consumes confirmed candidate evidence, the base resume, and a normalized job requirement profile. It produces a plan, a resume variant, a claim ledger, a verification report, keyword coverage, and a human-readable diff.

The optimizer is detailed in `2026-08-21-resume-optimizer-design.md`. It never sends an application and cannot create or confirm candidate evidence.

## 11. Human Approval Model

`ApplicationPackage` contains the normalized job, company, recruiter when available, full JD, match report, resume variant, resume diff, proposed message, and detected risks.

An `ApprovalRecord` binds approval to cryptographic digests of:

- application ID;
- normalized job and JD;
- resume variant;
- message;
- approval policy version.

Changing any bound artifact invalidates the approval. `application.send` accepts only a current approval and records both the validation result and delivery attempt.

Batch flow is:

```text
ResumeVariant
-> compatibility cluster
-> user selects jobs
-> batch preview
-> human approval
-> sequential send
-> audit
```

There is no `apply_all_matching_jobs` capability.

## 12. Audit Model

Every real or mock delivery attempt creates an append-only `ApplicationAudit` record containing job, platform, resume variant, message digest, approval record, attempt number, result, timestamp, and failure reason.

Audit queries support job, platform, failed-only, and date filters. Sensitive resume and message bodies are not duplicated in audit rows; immutable artifact IDs and digests provide traceability.

## 13. Skill and Context Architecture

The repository contains one discoverable `job-hunting` skill. Its entrypoint holds essential safety rules and routes to focused references. It does not contain browser automation or duplicate runtime business logic.

```text
skills/job-hunting/
├── SKILL.md
├── agents/openai.yaml
├── references/
│   ├── product-spec.md
│   ├── architecture-invariants.md
│   ├── capability-catalog.md
│   ├── candidate-kb.md
│   ├── evidence-policy.md
│   ├── job-intelligence.md
│   ├── resume-grounding.md
│   ├── hitl-approval.md
│   ├── connector-contract.md
│   ├── optimizer/
│   │   ├── workflow.md
│   │   ├── evidence-contract.md
│   │   ├── prompt-routing.md
│   │   ├── quality-gates.md
│   │   └── failure-handling.md
│   └── oss/
│       ├── source-manifest.yaml
│       ├── agentmesh-jobagent.md
│       ├── open-boss.md
│       └── auto-jobhunter.md
└── scripts/
    ├── sync_oss_context.py
    └── verify_oss_context.py
```

References are loaded only when their operating mode applies. The skill may be selected implicitly by its description or invoked explicitly as `$job-hunting`.

The OSS context manifest records repository URL, verified commit, verification date, license, reuse mode, allowed material, required attribution, prohibited use, and risk. Synced upstream research is stored under `.jobagent/cache/oss-context/` and ignored by Git.

Reuse policy:

- AgentMesh-JobAgent: Apache-2.0; adapter, subprocess, and interface research are permitted subject to attribution and notice obligations.
- open-boss: MIT; human approval, real-JD, dry-run, privacy, and platform-stop patterns may be studied and adapted with attribution where required.
- Auto-JobHunter: personal, educational, and non-commercial license; architecture-level reference only, with no source or prompt copying into this project.

## 14. Storage and Privacy

SQLite stores candidate records, evidence, jobs, job requirements, matches, resume variants, applications, approvals, and audits. Migrations are explicit and versioned.

The following never enter Git:

- source resumes and generated private variants;
- contact information exports;
- browser profiles and cookies;
- session tokens and API keys;
- local SQLite databases;
- synced OSS research caches;
- model request and response bodies containing private candidate data.

Secrets come from environment variables, OS keychain integration, or external connector configuration. `.env.example` contains names and descriptions but no credentials.

## 15. Error Model

Capabilities return typed domain failures. Failures are categorized as validation, missing evidence, conflict, policy rejection, user intervention, provider failure, platform change, stale approval, or storage failure.

Retries are allowed only for explicitly idempotent transient failures and are bounded by configuration. Approval, verification, risk-control, and platform-change failures are not retried automatically.

## 16. Testing Strategy

The suite includes:

- schema serialization and compatibility tests;
- domain unit tests;
- repository tests against temporary SQLite databases;
- connector contract tests shared by mock and real connectors;
- workflow tests using `MockJobSource`;
- approval digest and stale-approval tests;
- resume hallucination and semantic-exaggeration tests;
- skill validation and context-routing tests;
- privacy and secret-scanning tests.

Required acceptance cases include:

1. No RAG evidence prevents generation of a claim that the candidate built a RAG platform.
2. Modifying an approved resume invalidates the old approval.
3. CAPTCHA returns `USER_INTERVENTION_REQUIRED` and stops delivery.
4. Compatibility thresholds exclude the third of three otherwise strong candidate matches when only two resume compatibility scores qualify.
5. Cross-source deduplication preserves every source provenance record.

## 17. Delivery Phases

1. Repository bootstrap, architecture documents, schemas, and Skill Context skeleton.
2. Candidate profile, evidence, resume parsing, and adaptive interview.
3. JobSource protocol, mock connector, normalization, dedupe, hard filter, and matching.
4. Resume optimizer, verification, diff, rendering, and compatibility.
5. Application preview, digest approval, gated send, batch workflow, and audit.
6. Licensed OSS connector research and at least one real adapter.
7. Final Skill workflow, CLI examples, and open-source documentation.

Each phase ends with a testable deliverable, changed-file summary, test evidence, and architecture-invariant review.

## 18. Open-source Release Contract

The public repository includes README, LICENSE, CONTRIBUTING, SECURITY, PRIVACY, AGENTS, `.env.example`, examples, tests, and connector-development guidance.

The README describes what the product is, what it does not do, its evidence and human-approval model, privacy boundaries, connector architecture, quickstart, CLI examples, and extension points. Marketing language must not present the project as an automatic mass-application tool.
