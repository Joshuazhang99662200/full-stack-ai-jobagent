# Human-approved JobAgent

An evidence-grounded, human-approved AI job hunting agent.

JobAgent is a collection of atomic, auditable capabilities for candidate knowledge,
job intelligence, evidence-grounded resume optimization, application review, and
approved delivery. It is designed for use from Python, a CLI, MCP, and coding-agent
skills.

## What it is not

JobAgent is not an automatic mass-application bot. Search, matching, resume generation,
preview, approval, and delivery remain separate operations. Platform verification and
risk-control states stop the workflow for human intervention.

## Current phase

The architecture contracts, Candidate Core, offline Job Intelligence, and the Resume
Optimizer Phase 1 capability index are implemented.
Candidate Core can parse PDF resumes with page provenance, persist private candidate
knowledge in local SQLite, import structured reasoning drafts, detect gaps, ask one adaptive
interview question, record draft evidence, confirm evidence explicitly, and report readiness.

Job Intelligence searches the bundled synthetic source, normalizes and deduplicates jobs,
preserves every source observation, validates reviewed requirement and evidence mappings,
runs deterministic hard filters, computes explainable match results, ranks eligible jobs, and
stores artifacts in SQLite. Real platform connectors, executable Optimizer adapters and
runtime prompts, and delivery gates remain separate later phases.

## Candidate Core quickstart

Install the package and development tools:

```powershell
python -m pip install -e ".[dev]"
```

Use a local database explicitly while developing:

```powershell
jobagent candidate ingest CAND_001 .\candidate\private\source_resume.pdf `
  --database .\.jobagent\jobagent.sqlite3

jobagent candidate import-draft .\candidate\private\candidate-draft.json `
  --database .\.jobagent\jobagent.sqlite3

jobagent candidate question CAND_001 --target-role "Python Engineer" `
  --database .\.jobagent\jobagent.sqlite3

jobagent candidate status CAND_001 --target-role "Python Engineer" `
  --database .\.jobagent\jobagent.sqlite3
```

`ingest` only extracts local PDF text and provenance. `import-draft` accepts the typed
`CandidateDraft` JSON produced by a reviewed provider or test fixture. Model-produced and
interview-produced evidence stays unconfirmed until `jobagent candidate confirm` is called
for a specific `EVID_*` ID. Every command emits JSON by default.

Candidate source files, SQLite databases, and structured drafts can contain personal data;
keep them under ignored local paths such as `candidate/private/` and `.jobagent/`.

## Job Intelligence quickstart

The bundled fixture contains synthetic records and supports a fully local discovery path:

```powershell
jobagent jobs search python
jobagent jobs fetch alpha-001
jobagent jobs normalize alpha-001
jobagent jobs dedupe alpha-001 beta-991
```

Reasoning-dependent commands consume reviewed typed JSON. This keeps provider output at an
explicit validation boundary:

```powershell
jobagent jobs requirements alpha-001 .\reviewed\requirements.json

jobagent jobs filter alpha-001 .\reviewed\requirements.json `
  .\candidate\private\filter-context.json

jobagent jobs match alpha-001 .\reviewed\requirements.json `
  .\reviewed\mappings.json CAND_001 --database .\.jobagent\jobagent.sqlite3
```

For `jobs pipeline`, place reviewed files under one directory using
`JOB_ID.requirements.json` and `JOB_ID.matches.json`. A rejected job needs no mappings file
because deterministic filtering stops it before matching. Pipeline output always has
`application_ready: false`; `REVIEW` remains visible for human resolution.

Search and Job Intelligence are read-only. They do not expose platform navigation,
application preparation, approval, or delivery operations.

## Resume Optimizer capability discovery

Inspect the checked-in Optimizer capability and policy metadata without executing an
indexed entrypoint:

```powershell
jobagent optimizer capabilities
jobagent optimizer capabilities --kind policy
jobagent optimizer capabilities --intent detect_candidate_evidence_gaps
```

This Phase 1 command is read-only discovery. It validates and reports the L0 index while
leaving selected policy and Skill content unloaded. A later Router phase will load only the
selected resources and add executable adapters. Application approval, delivery, connector,
browser, login, and CAPTCHA behavior remain outside the Resume Optimizer boundary.

See [the architecture design](docs/superpowers/specs/2026-08-21-jobagent-foundation-design.md)
[the Job Intelligence design](docs/superpowers/specs/2026-08-21-job-intelligence-design.md),
and [the optimizer design](docs/superpowers/specs/2026-08-22-resume-optimizer-router-skill-design.md).
