# Channel-aware job dialogs implementation plan

> **For agentic workers:** Use executing-plans to implement the approved design task by task. User has requested direct implementation in this chat.

**Goal:** Show a job's channel in the primary list and open its channel-specific details in an accessible dialog.

**Architecture:** Presentation routing consumes existing job fields without redefining business models or writing business state. A native dialog contains progress, materials, history, linked observations and original records. Liepin omits greeting steps from the business UI, while the original-record inspector preserves source data.

**Tech Stack:** React, TypeScript, native HTML dialog, Playwright.

## Constraints

- Keep the approved white, gray and pale-blue palette.
- No invented timestamps, signals, approvals, attachments, SQL joins or execution capabilities.
- This revision changes the frontend; real SQL restoration remains private and requires a separate backend adapter before the production console can query it.
- The user requested a PR. Keep this revision separate from the existing open Agent-report PR and state its dependency.

## Task 1: Channel badges and accessible dialogs

- [x] Add failing Playwright cases for a visible channel, no bottom details before selection, dialog open/close, Escape and focus restoration.
- [x] Create a reusable native dialog wrapper in `frontend/src/JobDialog.tsx`.
- [x] Replace the bottom detail section in `frontend/src/JobQueue.tsx` with a dialog opened by the job, channel or actionable attention label.
- [x] Add responsive styles in `frontend/src/styles.css`; keep business history and exact fields accessible via dialog tabs.

## Task 2: Channel-specific content

- [x] Add a failing Liepin fixture: business UI excludes greetings, materials route is visible, raw source remains inspectable.
- [x] Create presentation-only routing in `frontend/src/channels.ts`; default and Liepin routes share layout but display different applicable sections.
- [x] Keep unbound observations and unavailable signal/harness sources explicit. Show actual linked runs and artifacts when present.
- [x] Update affected existing tests and frontend documentation.
- [x] Run all browser tests, app/library/declaration builds and SSR smoke. Run repository gates: pytest, Ruff, mypy, diff check.

## Task 3: Workflow footer requested during PR preparation

- [x] Add failing browser cases for completion, concurrent current work, missing observations, stale/failed work and closed jobs.
- [x] Keep the workflow below every detail tab. Blue means recorded completion, gray means planned or unrecorded, and outlined current nodes say “现在”.
- [x] Preserve channel routing, parallel observations and missing-data distinctions; do not infer earlier completion from pipeline order.
- [x] Rebuild and run frontend regression checks; review the preview before committing and opening the PR. Final checks: 27 browser cases, app/library/declaration builds, SSR, Ruff and mypy passed. The preceding full Python gate passed 1815 tests; this footer adds no Python changes.
