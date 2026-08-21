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

The repository currently establishes architecture and typed domain contracts. Runtime
candidate workflows, mock connectors, optimizer prompts, persistence, and delivery gates
are added in later independently tested phases.

See [the architecture design](docs/superpowers/specs/2026-08-21-jobagent-foundation-design.md)
and [the optimizer design](docs/superpowers/specs/2026-08-21-resume-optimizer-design.md).
