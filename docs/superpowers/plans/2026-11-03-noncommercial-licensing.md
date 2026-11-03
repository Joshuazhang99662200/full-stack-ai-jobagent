# Noncommercial Licensing Transition Plan

> Execute inline with writing-plans, test-driven-development and verification-before-completion. Do not commit or publish without a separate user request.

**Goal:** Offer free use under the unchanged PolyForm Noncommercial 1.0.0 license, including its educational and charitable organization permissions, with a separately negotiated paid commercial license.

**Architecture:** Keep the standard license text intact. Document the commercial route and historical Apache rights separately. Preserve third-party terms and carry the applicable legal files in distributable packages.

**Scope:** Licensing, package metadata, release packaging and contributor guidance only. No changes to evidence, approvals, platform access or memory behavior.

## Tasks

- [x] Inspect the current license, declarations, third-party notices and contributor history; verify primary Apache, OSI, PolyForm and Python packaging sources.
- [x] Confirm the free-use boundary with the owner: all noncommercial purposes, including schools and charities.
- [x] Run the existing documentation and standalone distribution tests as a baseline.
- [x] Add a failing distribution regression: licenses and notices must survive an independent skill build, remain byte-identical and participate in the integrity manifest. Missing required legal files must fail before output creation.
- [x] Replace `LICENSE` with the unmodified official PolyForm text; retain the old Apache text in `LICENSES/Apache-2.0.txt`. Add `NOTICE`, `COMMERCIAL_LICENSE.md` and `docs/licensing.md`.
- [x] Update `README.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, Python license metadata, frontend root package metadata and the relevant source-onboarding documents. Preserve every dependency's own license entry.
- [x] In `scripts/build_skill.py`, include exactly `LICENSE`, `NOTICE`, `COMMERCIAL_LICENSE.md` and `LICENSES/Apache-2.0.txt`. Update synthetic release fixtures and run the distribution regressions.
- [x] Build wheel and sdist with the installed Hatchling backend; inspect metadata and legal file bytes. Verify the official license digest and unchanged third-party notices.
- [x] Verify the frontend build in a private copy, keeping live preview outputs untouched: observe missing artifact licenses first, then copy the required legal files and runtime notices into both `dist/` and `lib/` and verify exact bytes after rebuilding.
- [x] Run the full repository gates and record the actual outcomes. Leave changes local for review.

## Publishing boundaries

The change cannot revoke existing Apache grants or relicense third-party code. Commercial terms require a separate executed agreement and payment as agreed; a download, issue, quote or donation does not grant commercial rights. External contributors must provide sufficient separate authorization before their work is included in a commercially licensed distribution. Git authorship is not proof of copyright ownership.

## Verified Results

- Baseline documentation/distribution checks: 26 passed.
- TDD: 3 intended failures, then 29 documentation/distribution checks passed.
- Full regression: 1866 passed, 2 skipped; 619.12 seconds. Both skips concern local symlink privileges.
- Ruff, strict mypy (253 source files), diff and new-file whitespace checks passed.
- Official license bytes, preserved Apache bytes and third-party notices verified unchanged.
- Built wheel, fixed sdist and isolated frontend app/library; verified legal file bytes and metadata. The first sdist included 8 private-workspace template files; it was quarantined locally, exclusion rules were added and the rebuilt archive passed. No artifact was uploaded.
- Changes remain uncommitted and unpublished.
