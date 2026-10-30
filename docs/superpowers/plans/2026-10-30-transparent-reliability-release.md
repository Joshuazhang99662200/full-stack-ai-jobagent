# Transparent Reliability Release Implementation Plan

> Execute inline with test-driven development. The user approved the preceding private assessment and explicitly requested implementation, a version iteration, anonymization, and support beyond PM roles. Do not commit, push, publish, modify live candidate state, or call recruiting platforms.

**Goal:** Ship a locally reviewable 0.2.0 release with explicit sourcing state, immutable observations, bounded reads, isolated feedback, delivery artifact checks, and role-neutral public guidance.

**Architecture:** Keep all contracts under schemas. Domain logic remains free of storage/browser dependencies. Storage owns transactions and history; host adapters perform authorized reads and report typed observations. Approvals remain separate from execution and platform capability limitations remain explicit.

**Tech Stack:** Python 3.11+, Pydantic, SQLite, Typer, pytest, Ruff, mypy; existing PDF/Word optional dependencies only.

## Global Constraints

- Preserve existing working-tree changes. Package only whitelisted public runtime/policies with privacy checks; never copy candidate/private, databases, credentials, actual resumes, or host state.
- Role selection, salary floor, geography, and source selection come from explicit candidate configuration. No built-in PM-only filter or personal outreach wording.
- Maintain approval digests, immutable evidence confirmation, per-action gates and no automatic retry on login/risk/unknown outcomes.
- Keep source detail ceiling at 50. No new bulk application orchestration or live migrations.
- Every behavioral change starts with a failing regression test. Additive SQL migration only; old observations cannot gain invented completeness or timestamps.

## Task 1: Provider errors and multilingual deduplication

- [x] Extend tests/connectors/test_cli_listing_source.py with zero-exit business-error envelopes and assert UserInterventionRequiredError with no retries; reject unknown failure envelopes even when jobs=[] exists.
- [x] Extend tests/jobs/test_deduplication.py with distinct Chinese duties, identical Chinese text and mixed-language low-overlap cases.
- [x] Run these tests and capture the expected failures, then fix src/jobagent/connectors/cli_source.py and src/jobagent/jobs/deduplication.py.
- [x] Run `python -m pytest -q tests/connectors tests/jobs/test_deduplication.py --basetemp candidate/private/t-r1`.

## Task 2: Scoped, stable feedback

- [x] Add tests that repeated calls with no changed inputs keep the same version, candidate/actor scope excludes foreign and unbound events, duplicate keys with changed content fail, and failed persistence cannot activate a plan.
- [x] Update schemas/sourcing_feedback.py, jobs/sourcing_feedback.py, bridge/sourcing_feedback.py and storage/feedback_repository.py with explicit scope and atomic activation/consumption records.
- [x] Preserve deterministic legacy calculations for unbound legacy callers; reject mixed scopes rather than inferring ownership.
- [x] Run the feedback and paged-card tests; the same scoped event set must produce one content version independent of parent lineage.

## Task 3: Observation identity, panel provenance and historical storage

- [x] Add contract/import tests for panel records with exact platform ID and actual search URL, partial/unloaded rejection, stable identity after salary/JD changes, and exact raw text preservation.
- [x] Add immutable job observation history in migration 0029 (renumbered after published main migrations during integration); preserve latest normalized view and legacy records without labeling old raw text complete.
- [x] Update SourceJobRecord, NormalizedJob, HostBrowserSpec, observation validation, normalizer, repository, CLI import and worker transaction. Store raw input and normalized view in one transaction.
- [x] Readback must expose version IDs and content digests without printing JD text. Preserve historical search hits and contact history.
- [x] Run storage/import/worker tests, including transaction rollback and replay idempotency.

## Task 4: Explicit attempt budgets and coverage

- [x] Add tests for atomic idempotent read reservations, profile mismatch, repeated failed reads consuming capacity, concurrent limit enforcement and login/risk stop behavior.
- [x] Implement typed read request/result, coverage and access-state contracts; persistent attempt ledger; jobs reserve-read and record-read commands; sourcing-budget reports actual attempts and legacy-count provenance.
- [x] Keep partial coverage and unknown states visible. Every input in a completion report must have a disposition; no loaded-empty inference from login/loading.
- [x] Update capability catalog with exact CLI surface and tests/test_capability_status.py must pass.

## Task 5: Employer artifact integrity

- [x] Add tests proving visible internal notes, PDF annotations/attachments and Word comments/revisions/hidden text cannot pass a final-artifact check; final byte replacement invalidates a bound artifact.
- [x] Implement final-artifact contracts/checks using existing optional libraries and bind actual bytes at the CLI delivery boundary. Keep old unsupported delivery routes stopped.
- [x] Ensure checks never rewrite or sanitize a candidate artifact silently: report issues for review and require fresh approval after changes.
- [x] Run harness/application/conversation regression tests.

## Task 6: Public role neutrality and release privacy

- [x] Add role-neutral regression examples spanning engineering, research, design, finance and operations, retaining configuration-driven exclusions.
- [x] Remove PM-only operational defaults from public browser sourcing guidance; fix stale Liepin detail and host drafting routes; add short generic invariants to AGENTS.md.
- [x] Add build-time privacy checks for public distribution contents, with synthetic leakage tests; emit identifiers/locations only, never matched secret values.
- [x] Bump pyproject.toml and jobagent.__version__ together from 0.1.0 to 0.2.0. Add Chinese release notes and an explicit implemented/deferred matrix.

## Task 7: Verification and local delivery

- [x] Run `python -m pytest -q --basetemp candidate/private/t-release-final`, `python -m ruff check .`, `python -m mypy src/jobagent`, `git diff --check`.
- [x] Build versioned Codex and Claude skill archives in ignored dist/, verify every manifest hash and run standalone integrity/metadata probes. No package installation into host directories.
- [x] Scan actual archive entries and public changed files for private paths, credentials, personal identifiers and forbidden runtime state. Keep the detailed privacy report private.
- [x] Report exact checks, version, archives, capability limits and unresolved host-only items. Do not claim real-platform integration from synthetic tests.

## Final Verification

1135 tests passed; Ruff, mypy (156 source files), and diff checks passed. Both 0.2.0 host archives passed hash, privacy, standalone metadata, and current-source consistency checks. Local working-tree delivery only; no commit, push, host installation, live state migration, or platform operation. Private delivery evidence is stored under candidate/private/codex-harness/reviews/.


## GitHub integration follow-up

The owner subsequently authorized committing, pushing and merging the completed changes. The local-only validation above records the earlier delivery stage. Integration preserves the published main branch and its migrations 0001-0026; worker, paged feedback, reliability and dynamic rules append as 0027-0030. Conflicting unpublished local schema numbering is rejected before migration. Both sourcing entry points share daily usage and gate halts; observation history and JD snapshots commit atomically. Dynamic evaluators remain distinct from the persistent pipeline consumers as documented.

The merged tree passed all 1656 tests. Privacy scanning covered 614 public text files with no unresolved findings; six deliberate negative-test fixtures remain documented. No personal database migration, task changes or recruitment-platform actions were performed.
