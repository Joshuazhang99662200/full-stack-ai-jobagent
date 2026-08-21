# Candidate Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Every production change follows a red-green-refactor cycle.

**Goal:** Deliver a local-first Candidate Core that parses PDF resumes, stores candidate knowledge and evidence in SQLite, creates structured drafts through a provider-neutral reasoning boundary, detects material gaps, asks one adaptive question at a time, and reports evidence readiness.

**Architecture:** PDF extraction is deterministic infrastructure. Candidate fact extraction is a typed reasoning capability and never silently falls back to regex-generated claims. Application services coordinate parser, extractor, evidence policy, and repository ports. SQLite stores private operational data behind repositories; domain modules remain independent from SQLite, Typer, pypdf, and provider SDKs.

**Tech Stack:** Python 3.11+, Pydantic v2, stdlib `sqlite3`, pypdf 6.x, Typer, pytest, ReportLab test fixtures, Ruff, mypy

## Phase Boundary

This phase includes:

- versioned resume-ingestion and interview contracts;
- PDF text extraction with page provenance and SHA-256 digest;
- explicit SQLite migration and candidate repository;
- reasoning-backed draft extraction with a fake provider for offline tests;
- evidence confirmation and conflict-safe updates;
- deterministic gap detection, one-question selection, and readiness reporting;
- a small Candidate CLI for local ingestion, structured draft import, interview, and status;
- an end-to-end offline Candidate Core workflow test.

This phase defers job-source connectors, JD normalization, matching, runtime optimizer prompts, application approval, and delivery. It also defers a production model-provider adapter: the extractor port and fake provider are delivered now so a later provider can be added without changing Candidate Core.

## Architectural Invariants

- `CandidateProfile != Resume`; resume pages are source artifacts, not the canonical profile.
- Resume parsing may extract text but may not invent candidate facts.
- Reasoning output enters storage as draft evidence and remains unconfirmed.
- Only an explicit user confirmation can set `user_confirmed=True`.
- Weak evidence cannot be confirmed.
- Skipping a question preserves the gap and records no fabricated answer.
- One interview selection returns at most one question.
- SQLite files and source resumes remain ignored by Git.
- Domain and application packages do not import provider SDKs or browser automation.

## File Map

```text
pyproject.toml                                  pypdf runtime and ReportLab test dependency
src/jobagent/schemas/candidate.py              Resume, draft, interview, and status contracts
src/jobagent/candidate/ports.py                Parser, extractor, and repository protocols
src/jobagent/candidate/onboarding.py           Parse/extract/persist orchestration
src/jobagent/candidate/evidence.py             Evidence confirmation and update policy
src/jobagent/candidate/gaps.py                 Deterministic gap detection
src/jobagent/candidate/interview.py            Single-question selection and answer handling
src/jobagent/candidate/readiness.py            Candidate status calculation
src/jobagent/storage/database.py               SQLite connection and migration runner
src/jobagent/storage/migrations/0001_candidate.sql
src/jobagent/storage/candidate_repository.py   SQLite repository adapter
src/jobagent/parsing/pdf_resume.py             pypdf adapter
src/jobagent/reasoning/candidate_extractor.py  ReasoningProvider-backed draft extractor
src/jobagent/cli/app.py                        Root Typer application
src/jobagent/cli/candidate.py                  Candidate subcommands
tests/candidate/*                              Candidate domain/application tests
tests/storage/*                                Migration and repository tests
tests/parsing/*                                Real PDF extraction tests
tests/reasoning/*                              Structured extraction tests
tests/cli/*                                    Candidate CLI tests
tests/workflows/test_candidate_core.py         Offline phase acceptance test
```

### Task 1: Resume and Interview Contracts

**Files:**
- Modify: `src/jobagent/schemas/candidate.py`
- Test: `tests/schemas/test_candidate.py`

**Interfaces:**
- Produces `ResumePage`, `ParsedResume`, `CandidateDraft`, `InterviewQuestion`, `InterviewAnswer`, and `CandidateStatus`.

- [ ] Write failing tests for page numbering, digest format, candidate/evidence ID consistency, skipped-answer validation, and one primary gap per question.
- [ ] Run `python -m pytest tests/schemas/test_candidate.py -q` and confirm the new imports fail.
- [ ] Implement the minimum contracts and validators.
- [ ] Re-run the focused tests and confirm green.
- [ ] Commit with `feat: add candidate onboarding contracts`.

### Task 2: SQLite Migration Boundary

**Files:**
- Create: `src/jobagent/storage/__init__.py`
- Create: `src/jobagent/storage/database.py`
- Create: `src/jobagent/storage/migrations/__init__.py`
- Create: `src/jobagent/storage/migrations/0001_candidate.sql`
- Test: `tests/storage/test_database.py`

**Interfaces:**
- Produces `Database.connect()` and `Database.migrate()` with foreign keys enabled and a versioned schema.
- Tables: `candidate_profiles`, `evidence_items`, `resume_ingestions`, and `interview_events`.

- [ ] Write a failing temporary-database migration test.
- [ ] Confirm the missing storage module failure.
- [ ] Implement explicit, idempotent migration execution and translate `sqlite3.Error` to `StorageError`.
- [ ] Verify schema version and foreign-key enforcement.
- [ ] Commit with `feat: add candidate sqlite migration`.

### Task 3: Candidate Repository Adapter

**Files:**
- Create: `src/jobagent/candidate/__init__.py`
- Create: `src/jobagent/candidate/ports.py`
- Create: `src/jobagent/storage/candidate_repository.py`
- Test: `tests/storage/test_candidate_repository.py`

**Interfaces:**
- Produces a `CandidateRepository` protocol and `SqliteCandidateRepository` adapter.
- Supports profile save/load, evidence upsert/get/list, resume-ingestion save/load, and append-only interview events.

- [ ] Write failing round-trip, upsert, isolation, missing-record, and append-only tests.
- [ ] Confirm failures before implementation.
- [ ] Implement JSON serialization through Pydantic contracts and parameterized SQL only.
- [ ] Re-run focused tests and strict type checking for the new modules.
- [ ] Commit with `feat: persist candidate knowledge in sqlite`.

### Task 4: PDF Resume Parser

**Files:**
- Modify: `pyproject.toml`
- Create: `src/jobagent/parsing/__init__.py`
- Create: `src/jobagent/parsing/pdf_resume.py`
- Test: `tests/parsing/test_pdf_resume.py`

**Interfaces:**
- Implements `ResumeParser.parse(path, candidate_id) -> ParsedResume`.
- Computes a content digest, extracts page text in order, records page-local warnings, and never changes the source file.

- [ ] Add a ReportLab-generated two-page PDF test fixture and failing parser tests.
- [ ] Confirm the parser import fails.
- [ ] Add compatible dependency ranges and implement pypdf extraction.
- [ ] Verify missing files, encrypted files, and pages without text produce typed outcomes.
- [ ] Commit with `feat: parse resumes with page provenance`.

### Task 5: Reasoning-backed Candidate Draft Extraction

**Files:**
- Create: `src/jobagent/reasoning/__init__.py`
- Create: `src/jobagent/reasoning/candidate_extractor.py`
- Test: `tests/reasoning/test_candidate_extractor.py`

**Interfaces:**
- Implements `CandidateDraftExtractor` using the existing `ReasoningProvider`.
- Uses prompt ID `candidate.extract_draft.v1` and requires a typed `CandidateDraft` response.

- [ ] Write a fake-provider test that captures prompt ID/context and returns a structured draft.
- [ ] Add a rejection test for mismatched candidate IDs and confirmed model-produced evidence.
- [ ] Implement the adapter and deterministic post-validation; model output is always draft/unconfirmed.
- [ ] Re-run focused tests.
- [ ] Commit with `feat: extract grounded candidate drafts`.

### Task 6: Candidate Onboarding Service

**Files:**
- Create: `src/jobagent/candidate/onboarding.py`
- Test: `tests/candidate/test_onboarding.py`

**Interfaces:**
- Produces `CandidateOnboardingService.ingest_resume(...) -> CandidateDraft`.
- Coordinates parser, extractor, and repository without embedding provider or SQLite details.

- [ ] Write a failing orchestration test with fake ports.
- [ ] Assert extraction failure causes no partial profile/evidence commit.
- [ ] Implement successful atomic persistence through a repository transaction method.
- [ ] Re-run focused tests.
- [ ] Commit with `feat: orchestrate candidate onboarding`.

### Task 7: Evidence Lifecycle Service

**Files:**
- Create: `src/jobagent/candidate/evidence.py`
- Test: `tests/candidate/test_evidence.py`

**Interfaces:**
- Produces explicit `add_draft`, `confirm`, and `replace_with_user_edit` operations.
- Confirmation preserves provenance, refuses weak evidence, and refuses cross-candidate updates.

- [ ] Write failing confirmation, weak-evidence, unknown-ID, and user-edit tests.
- [ ] Implement the minimum service and typed policy errors.
- [ ] Verify only explicit confirmation changes `user_confirmed`.
- [ ] Re-run focused tests.
- [ ] Commit with `feat: enforce candidate evidence lifecycle`.

### Task 8: Gap Detection and Adaptive Interview

**Files:**
- Create: `src/jobagent/candidate/gaps.py`
- Create: `src/jobagent/candidate/interview.py`
- Test: `tests/candidate/test_gaps.py`
- Test: `tests/candidate/test_interview.py`

**Interfaces:**
- Produces deterministic `GapDetector.detect(...)` and `AdaptiveInterview.next_question(...)`.
- Scores priority, target-role relevance, evidence weakness, information gain, and repetition penalty; returns zero or one question.

- [ ] Write failing tests for missing identity/experience, high-value weak evidence, role relevance, repetition avoidance, skip behavior, and single-question output.
- [ ] Implement deterministic rules and stable tie-breaking.
- [ ] Convert an answer into unconfirmed interview evidence; skipped answers create only an event.
- [ ] Re-run focused tests.
- [ ] Commit with `feat: add adaptive candidate interview`.

### Task 9: Candidate Readiness and Status

**Files:**
- Create: `src/jobagent/candidate/readiness.py`
- Test: `tests/candidate/test_readiness.py`

**Interfaces:**
- Produces `CandidateReadinessService.evaluate(...) -> CandidateStatus` with descriptive completeness and target-role readiness.

- [ ] Write failing tests for empty, partial, and evidence-confirmed candidates.
- [ ] Implement documented deterministic weights with values bounded to `[0, 1]`.
- [ ] Ensure unknown fields reduce readiness without encouraging invented values.
- [ ] Re-run focused tests.
- [ ] Commit with `feat: report candidate evidence readiness`.

### Task 10: Local Candidate CLI

**Files:**
- Create: `src/jobagent/cli/__init__.py`
- Create: `src/jobagent/cli/app.py`
- Create: `src/jobagent/cli/candidate.py`
- Modify: `pyproject.toml`
- Test: `tests/cli/test_candidate.py`

**Interfaces:**
- Adds `jobagent candidate ingest`, `import-draft`, `question`, `answer`, and `status`.
- `ingest` parses and stores the resume source; `import-draft` imports a reviewed structured draft for provider-free local use. No command confirms evidence implicitly.

- [ ] Write failing Typer runner tests using a temporary database and PDF.
- [ ] Implement thin commands over application services/repositories.
- [ ] Make machine-readable JSON the stable default output.
- [ ] Verify errors return non-zero exit codes without leaking resume bodies.
- [ ] Commit with `feat: expose candidate core cli`.

### Task 11: Offline Candidate Core Acceptance

**Files:**
- Create: `tests/workflows/test_candidate_core.py`
- Modify: `README.md`
- Modify: `skills/job-hunting/references/candidate-kb.md`
- Modify: `skills/job-hunting/references/evidence-policy.md`

**Acceptance flow:**

```text
two-page PDF
-> ParsedResume with digest and page provenance
-> fake reasoning CandidateDraft
-> SQLite persistence
-> CandidateGap list
-> one InterviewQuestion
-> unconfirmed interview EvidenceItem
-> explicit confirmation
-> improved CandidateStatus
```

- [ ] Write the failing workflow test before documentation changes.
- [ ] Implement only missing integration glue.
- [ ] Document the exact offline workflow and evidence confirmation boundary.
- [ ] Run the workflow test and all Candidate Core tests.
- [ ] Commit with `test: complete candidate core workflow`.

### Task 12: Phase Quality Gate

- [ ] Run `python -m pytest -q`.
- [ ] Run `python -m ruff check .`.
- [ ] Run `python -m ruff format --check .`.
- [ ] Run `python -m mypy src`.
- [ ] Run the JobAgent Skill quick validator.
- [ ] Inspect `git status --short --ignored` and confirm no resume, database, or private payload is tracked.
- [ ] Review the phase against every architectural invariant above.
- [ ] Commit verification-only corrections if required; do not create an empty commit.

## Plan Self-review Result

- The plan keeps deterministic parsing separate from claim extraction.
- The repository is local-first, versioned, and private-artifact aware.
- The model can propose only draft evidence; confirmation remains a human action.
- Interview selection is adaptive and returns one question at a time.
- The CLI remains thin and offers a provider-free structured import path without pretending heuristic text extraction is trustworthy.
- Resume optimization and application side effects stay outside Candidate Core.
