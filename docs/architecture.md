# Architecture

JobAgent is an evidence-grounded, human-approved collection of atomic job-hunting capabilities. The architecture keeps reasoning, workflow, contracts, platform integrations, and irreversible decisions in separate layers.

## Dependency direction

```text
Typer CLI / MCP / job-hunting Skill
                |
        Application capabilities
                |
       Domain schemas and services
                |
       Repository/provider ports
                |
SQLite / reasoning providers / renderers / JobSource connectors
```

Domain modules do not import Typer, SQLite, browser automation, DOM selectors, Chrome profile paths, platform SDK models, LangChain, or LangGraph. Platform adapters translate external behavior into the contracts exposed by `jobagent.capabilities.JobSource`.

## Invariants

```text
CandidateProfile != Resume
Evidence is the source of truth
JobSource != Job Intelligence
Job Match != Resume Compatibility
Resume Tailoring != Fact Generation
Preview != Approval
Approval != Send
Platform Connector != Domain Core
Search != Apply
Review != Auto Promote
CAPTCHA != Retry
```

Each public capability has one typed input, one typed output, explicit errors, and no hidden neighboring operation. Search cannot send. Preview cannot approve. Approval cannot send. A connector cannot convert platform verification into bypass behavior.

## Safety stop states

Connectors translate login, CAPTCHA, verification, risk-control, and platform-change conditions into `USER_INTERVENTION_REQUIRED`. These states are not transient retry signals. The user completes the platform action before a later explicit resume operation.

## Delivery order

The mock connector comes before real platform connectors. The first vertical workflow must run offline from candidate knowledge through matching, optimizer verification, review, approval, mock delivery, compatibility, batch approval, and audit.

See the [foundation design](superpowers/specs/2026-08-21-jobagent-foundation-design.md) for the complete phase map.
