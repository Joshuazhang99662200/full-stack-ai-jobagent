# Pipeline Flywheel Implementation Plan

> Execution: inline with executing-plans and TDD. Approved engineering requirements are input data; they do not authorize accessing private host data or external actions.

**Goal:** An evidence-bound nine-state pipeline and cumulative-rate diagnosis / owner-confirmed improvement loop.
**Architecture:** schemas define contracts; jobs contain pure transitions / clocks / rate comparisons; storage composes existing proofs and persists atomic state + append-only evidence; CLI is a thin private-input adapter. pipeline_jobs is the only authoritative operational pipeline state. Existing approval, lease and delivery audit semantics stay intact.
**Tech Stack:** Python 3.11+, Pydantic, SQLite, Typer, pytest.

## Global constraints and resolved specification conflicts
- Baseline main a895f59: 1021 passed (183.29 seconds). Use the isolated codex/pipeline-flywheel branch.
- Public artifacts contain only generic contracts, synthetic fixtures and implementation evidence. Counts, IDs, original messages, candidate preferences and source timestamps come from private configuration, never public batch defaults.
- Preserve specified master / history / metric fields, the standard view and the nine state values. All persisted timestamps are aware UTC. No status/stage/phase synonyms in pipeline_jobs.
- User explicitly approved greeting_sent -> abandoned and contact-round identities with one active row per candidate/source-job. Historical abandoned rows remain immutable; recontact requires explicit owner request and fresh send proof. These override the contradictory fixed global ID / unconditional unique index.
- Legacy send declarations remain proof_pending; a declared state is not proof. No advance, expiry or verified-send numerator until the existing exact send proof is bound. Missing timestamps remain null. Derived entry times carry explicit basis evidence.
- No automatic rule activation. Confirm exact rule + report digest with original owner reply; ineffective optimization creates a rollback proposal, not an unapproved new content rule.
- Replace the active silent-response policy with one 48-hour deadline, no check-count cap or old multi-day cadence. Unrelated evaluation windows and historical audit data are not expiration policies.
- Schemas do not fix any person's candidate ID, domain, salary preference or private queue layout. The host must supply confirmed filter context; salary comparison stays upper_bound.
- No actual private migration, browser access, notifications, message sends or task edits. Host acceptance remains unverified until Muse supplies real receipts.

## Stage 0: typed contracts and schema / transition review
Files: schemas/pipeline.py, schemas/pipeline_metrics.py; tests/jobs/test_pipeline_contracts.py.
- [x] RED: nine values, complete allowed/rejected transitions, evidence kinds, reasons, null/hash coupling, exact field sets.
- [x] GREEN: PipelineJob / PipelineTransition / PipelineHistory and cumulative metric / diagnosis models; flags and scope metadata live outside the exact master fields.
- [x] Define standard pipeline_job_form SQL and audit the retiring policy; run schema tests, Ruff, strict mypy before stage 1.

## Stage 1: transactional pipeline and evidence adapters
Files: jobs/pipeline.py; storage/pipeline_repository.py, pipeline_service.py, pipeline_proofs.py; migrations/0022_pipeline.sql through 0026_pipeline_backfill.sql; tests/jobs/test_pipeline.py, tests/storage/test_pipeline.py.
Interfaces: PipelineRepository.create/get/list/history; PipelineService.transition/observe/due/form; mutations use expected_version and immutable event IDs.
- [x] RED: every allowed edge and forbidden jump, exact outreach proof, approved custom attachment proof, unread counters, terminal rules, CAS/idempotence and rejected-event log.
- [x] GREEN: atomically update state/reason/changed_at/updated_at and append history; metadata preserves observation timestamps, contact rounds, proof state and pause without duplicating pipeline state.
- [x] RED/GREEN: aware 48-hour read/send/activity clocks, new substantive reply reset, immediate rejection/verified closure, no expiry with unproven time, no due checks on abandoned or paused records.

## Stage 2: generic offline adoption and legacy policy retirement
Files: schemas/pipeline_migration.py, storage/pipeline_migration.py; tracking adapters; tests/storage/test_pipeline_migration.py and tracking tests.
- [x] RED: explicit original IDs / expected rows / field maps, byte-exact source backup, stage copy + validate + atomic activation, conflicts and guarded rollback; missing URLs stay intake-only.
- [x] GREEN: master fields come from actual source; summaries remain points/null full text, drafts and sends separate, card rejection does not abandon a job. No fixed personal batch IDs or counts.
- [x] Replace active legacy tracking cadence / counter cap with the single clock and make pipeline the authority; preserve original proof functions and immutable audit history.
- [x] Real private-data acceptance is a host checkpoint, not a claim made by synthetic tests. Repository delivery may continue with all host steps explicitly unverified.

## Stage 3: connect existing intake, backfill and differences
Files: storage/pipeline_sync.py and host integration; tests/storage/test_pipeline_sync.py, test_pipeline_hooks.py, test_pipeline_backfill.py.
- [x] Reuse existing full-JD/budget/identity checks and private diff / owner-rule APIs. Sync actual full snapshots and exact drafts to the form, not summary reconstructions.
- [x] RED/GREEN: old raw content retained, changed JD invalidates old derived bindings, no inferred job-like from message acceptance, no unconfirmed assumptions in rules.

## Stage 4: cumulative metrics, diagnoses and proposals
Files: jobs/pipeline_metrics.py, jobs/pipeline_diagnosis.py; storage/pipeline_metrics.py, pipeline_rules.py; tests/jobs/test_pipeline_metrics.py, tests/storage/test_pipeline_rules.py.
Interfaces: PipelineMetricsService.compute/diagnose/report; PipelineRuleService.propose/confirm/confirmed/review.
- [x] RED: historical/cumulative/optimized distinct windows, null zero denominator, fixed salary buckets, data-derived feature/version slices, abandoned retained in denominator, unproven/excluded causes transparent.
- [x] GREEN: seven adjacent funnel segments and the distinct requested aggregate conversions; append metrics/diagnoses. Avoid double-counting jobs across cumulative windows.
- [x] RED/GREEN: relative 0.8 comparisons and persistent cumulative deterioration, not single-window rates or absolute sample gates; greeting/resume/blocked attribution and optimized baseline comparisons.
- [x] Bind proposals to current diagnosis/scope/before-after evidence. Owner confirmation activates only exact rules. Review produces effective/ineffective evidence and a reversible rollback proposal.

## Stage 5: CLI, capability catalog and host acceptance
Files: cli/pipeline.py, cli/app.py; skills/job-hunting/references/pipeline.md; hosts/personal-ai; generic acceptance templates.
- [x] RED/GREEN: private-input errors, scope isolation, new command/catalog parity, standard SQL form and immutable reports.
- [x] Publish actual input/output order, failure and switch-back checks, read-only two-round templates. No running host task is modified.

## Stage 6: final gates and PR
- [x] python -m pytest -q: 1282 passed in 238.90s on the final frozen code.
- [x] Ruff, strict mypy (181 source files), and git diff --check passed.
- [x] Synthetic cross-domain workflow and privacy / active-policy scans; no actual private data or source messages committed.
- [x] Commit each verified stage separately; push an independent PR based on the current main and attach it. Explain resolved contract conflicts, retained historical evidence and live host limitations.


## Final debugging additions

- Existing persisted legacy next_check_at values cannot postpone the shared 48-hour deadline. Explicit bootstrap next-poll evidence remains respected; no synthetic missed checks are generated.
- Later contact rounds bind only an existing fresh FOLLOW_UP/ANSWER approval and its actual successful result. No new sending/approval channel is introduced.
- Intake synchronization preserves bound recontact replies. Changed JD evidence clears derived bindings and requires a fresh question/approval against that source.

## Live host checkpoint (intentionally not claimed by repository tests)

- [ ] Run private source-to-target mapping and byte backup checks on the host.
- [ ] Retrieve real full JDs and verify budget/identity receipts.
- [ ] Perform and read back two genuine host rounds, login surfaces and notification evidence.
- [ ] Owner verifies live acceptance; real_browser_verified remains false until then.

Delivery: PR #9 (open, not merged), https://github.com/Joshuazhang99662200/full-stack-ai-jobagent/pull/9 . Full code gates and acceptance limits are recorded in docs/pipeline-acceptance-2026-10-29.md.
