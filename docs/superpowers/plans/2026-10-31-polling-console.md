# Polling Console Implementation Plan

> **For agentic workers:** Execute with test-driven development and independent Hallmark finish review.

**Goal:** Ship a reusable React polling console backed by candidate-scoped, read-only business projections and explicit host activity records.

**Architecture:** Python contracts remain authoritative. A read-only projection combines complete pipeline records and history with portable harness runs and optional activity observations. CLI, MCP and local HTTP consume the same projection. React accepts that snapshot as props; its standalone app loads the loopback endpoint or an explicitly selected synthetic fixture.

**Tech Stack:** React, TypeScript, Vite; Python standard-library HTTP and existing Pydantic contracts.

## Global Constraints

- Never change approvals, delivery, scheduling, private settings or production databases.
- Public examples are synthetic and explicitly labelled. No external fonts or runtime CDN dependencies.
- Missing/corrupt/incompatible sources are reported, never converted to successful empty results.
- Activities are host observations, not evidence of approval, sending or reading. No inferred durations or inferred intermediate pipeline states.
- Preserve complete business fields; credential configuration is never part of the read model.
- Local HTTP is GET-only and loopback-only, with Host/Origin validation and no arbitrary file serving.
- No commit or push in this iteration unless requested.

## Task 1: Authoritative read contracts and projection

Files: `src/jobagent/schemas/console.py`, `src/jobagent/console/projection.py`, `tests/console/test_projection.py`.

- [x] Write tests proving candidate isolation, full JD/draft preservation, history fidelity, missing-source diagnostics and zero database mutation.
- [x] Run `python -m pytest tests/console -q` and observe failure for the missing feature.
- [x] Implement snapshot and definitions from existing schema classes; read SQLite using `mode=ro`, with a consistent transaction; read harness state without acquiring a lease.
- [x] Re-run targeted tests and inspect serialized output for accidental information loss.

## Task 2: Host activity records and shared query entry points

Files: `src/jobagent/console/activities.py`, `src/jobagent/console/server.py`, `src/jobagent/cli/console.py`, root CLI registration, MCP tool registration and corresponding tests.

- [x] Test activity identity, immutable/idempotent events, timezone/chronology checks, foreign candidate rejection and stale heartbeat presentation.
- [x] Test GET snapshot/definitions, POST rejection, foreign Host/Origin rejection, missing static build and traversal rejection.
- [x] Implement host event ingestion as explicit private observations. Query operations never write, migrate, acknowledge events or consume leases.
- [x] Expose `console definitions`, `console list`, `console event`, `console serve`; mirror read queries in MCP.

## Task 3: React component and standalone app

Files: `frontend/` build configuration, `src/Console.tsx`, `src/contracts.ts`, `src/main.tsx`, `src/styles.css`, tests, synthetic fixture and README.

- [x] Write interaction tests for run selection, recorded-only nine-state paths, full field disclosure and load/error/empty states.
- [x] Implement controlled reusable components, URL-backed view selection and local data loading; no send/approve controls.
- [x] Build with locked dependencies. Preserve their license notices and register dependencies in the OSS review.

## Task 4: Integration and review

Files: capability catalog, AGENTS.md, `docs/polling-console.md`, OSS records, Hallmark review report.

- [x] Document host event lifecycle, startup and full JSON queries, component embedding, private data and source limitations.
- [x] Verify frontend type check/build/interaction checks and Python suite, Ruff, mypy and diff checks.
- [x] Run Hallmark app-scope static/render sweep; independent finish review; fix findings and recapture.
- [x] Deliver runnable commands, verified screenshots and exact remaining limitations.

## Verification evidence

- Baseline: 1796 passed, 520.09s; isolated repository basetemp avoids the Windows sandbox temp-directory restriction.
- Final Python suite: 1811 passed, 539.88s; real HTTP tests run outside the socket-restricted sandbox.
- Ruff clean; mypy clean on 243 source files; git diff check clean.
- React app/library/declaration build and SSR smoke passed; final independent browser run 13 passed in 13.4s.
- Hallmark confirmation: 15 screenshots, 0 FAIL, 0 REFLEX, 0 WARN; independent finish review's three findings resolved.
- Detailed handoff: `docs/polling-console.md`; review: `docs/reviews/2026-10-31-polling-console-hallmark.md`.
