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

The architecture contracts and Candidate Core are implemented. Candidate Core can parse
PDF resumes with page provenance, persist private candidate knowledge in local SQLite,
import structured reasoning drafts, detect gaps, ask one adaptive interview question,
record draft evidence, confirm evidence explicitly, and report readiness. Job connectors,
runtime optimizer prompts, and delivery gates remain later independently tested phases.

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

See [the architecture design](docs/superpowers/specs/2026-08-21-jobagent-foundation-design.md)
and [the optimizer design](docs/superpowers/specs/2026-08-21-resume-optimizer-design.md).
