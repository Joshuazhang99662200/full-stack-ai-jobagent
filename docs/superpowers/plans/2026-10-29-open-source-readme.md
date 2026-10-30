# CareerHarness README Implementation Plan

> **For agentic workers:** Execute this approved documentation plan inline, task by task, with verification before completion. Do not commit or push without a user request.

**Goal:** Deliver an illustrated Chinese README that explains the current job-search workflow and gives newcomers an honest first experience.

**Architecture:** Use repository-native SVG assets and Markdown. Move detailed CLI material to a separate usage guide, keep existing install identities, and align privacy documentation with current optional integrations.

**Tech Stack:** Markdown, accessible static SVG, Python CLI, local SVG rendering.

## Global Constraints

- Every claim must match the capability catalog and actual implementation.
- External sending requires individual human approval; diagrams cannot imply unattended delivery.
- Preserve existing worktree edits and personal data boundaries.
- No commits, pushes, remote rename, or new runtime dependencies.

## Tasks

- [x] Document the approved design and identify the baseline failure before editing.
- [x] Create `docs/assets/career-harness/hero.svg`, `evidence.svg`, and `approval.svg`; label synthetic illustrations.
- [x] Rewrite `README.md` and migrate detailed commands to `docs/usage.md`, correcting stale rendering and host claims.
- [x] Update `PRIVACY.md` for optional model, host, and Feishu data flows.
- [x] In `tests/bridge/test_preference_signals.py`, pass the existing fixture clock to the failing card event; verify the original test passes without changing production behavior.
- [x] Verify local Markdown links, SVG parsing, readonly quickstart output, and rendered graphics; run pytest, Ruff, mypy, and `git diff --check`.
- [x] Present the resulting README and preview with remaining release limitations.

The original failure is `test_raw_context_keeps_revision_requested_and_exact_original_revision_pair`: `populated()` uses 2026-10-26, but event handling defaults to the current clock. Explicitly passing the fixture time changes the synthetic result from `rejected` to `revision_requested`; the production expiry check stays intact.

## Verification record

- Original baseline: 1032 passed, 1 failed; isolated clock comparison confirmed the cause.
- Corrected test file: 18 passed. Full suite: 1033 passed in 145.11 seconds, using a workspace-local pytest base directory because the sandbox default temporary directory was unavailable.
- Ruff, strict mypy (151 source files), and `git diff --check` pass.
- 46 local Markdown links and fragments resolve; three SVG files parse without scripts or external resources; three quickstart commands produce the documented JSON.
- All three figures were rasterized and visually checked. A local GitHub-style Markdown preview loaded all figures at 1120px and 390px viewport widths, with no mobile horizontal overflow. This preview is not a screenshot of the hosted GitHub page.
- No remote rename, commit, or push. CI, tagged releases, and account-specific platform acceptance remain separate release work.
