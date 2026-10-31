# First-run Configuration Implementation Plan

> **For agentic workers:** Execute the approved design task by task with test-first implementation. Root owns sourcing integration; setup_core owns configuration contracts, state and CLI; setup_docs owns human-facing protocols. Preserve unrelated edits. Do not commit or push.

**Goal:** Configure once at first initialization, reload across later rounds/types/sessions without questions, reopen configuration only on an explicit owner request, and enforce the two confirmed sourcing quantities at real consumers.

**Architecture:** Authoritative Pydantic contracts remain under schemas. A pure preparation service distinguishes initialization, ordinary execution and owner-requested changes. Private SQLite records completion and existing single-variable confirmation/history. Typed sourcing rounds freeze the current confirmed rules; query capture and both detail entry points share versioned limits, receipts and intervention halts.

**Tech Stack:** Python, Pydantic, SQLite, Typer, pytest, Ruff, strict mypy.

## Constraints

- First initialization may ask unresolved values. Ordinary rounds, different task types, resumed sessions, missing fields and conflicts cannot generate configuration questions.
- Parameter changes require actual owner request evidence and the existing exact-question/confirmation chain. A round-only change cannot update the persistent head.
- No live candidate configuration, external platform operation, scheduler, notification delivery or database migration is performed during development.
- No personal public defaults, platform-limit bypass, automatic delivery, evidence promotion or terminal-history recalculation.
- Preparation is read-only and consumes no quota. Configured execution cannot silently use old defaults or switch to a larger policy.
- Existing source policies remain explicit. Existing production-pipeline conflict deficiencies are outside this feature and must remain honestly documented.

## Task 1: First-run preparation and persistent initialization

**Files:** schemas/dynamic_rules.py, new schemas/configuration.py, new rules/preparation.py, new storage/configuration_repository.py, storage/rule_repository.py, cli/rules.py, migration0031 and database registration, focused rules/storage/CLI tests.

**Interfaces:** OwnerChangeRequest(candidate_id, names, owner_text, source_reference, actor_id, requested_at, scope, run_id). ConfigurationPreparationRequest(candidate_id, task_id, task_type, mode, required_names, owner_request). SqliteConfigurationRepository.prepare(request), initialize(candidate_id, expected_version, now), and configuration_initialized(connection, candidate_id).

- [x] Write failing tests for unconfigured ordinary execution returning no questions, first initialization returning unresolved questions, persisted initialization across task types, explicit owner changes only, missing/conflict diagnostics, stale heads and private readonly preparation.
- [x] Observe expected failures before adding contracts and service.
- [x] Implement mode-driven preparation. Baseline sourcing quantities are always required; additional unsupported consumers block without changing ordinary-run mode.
- [x] Add append-only initialization records. Migration31 backfills existing confirmed profiles as initialized, including incomplete profiles, preventing unsolicited re-onboarding.
- [x] Guard proposal creation and confirmation after initialization with candidate/name/actor/time-bound owner request evidence. Persistent approval rejects round-only scope.
- [x] Expose rules prepare and rules initialize. A fully confirmed but uninitialized profile is ready_to_initialize with ready=false; completion records machine state without asking for the same owner decisions again.
- [x] Run focused tests and report the exact outcome.

Test boundary:

```python
result = prepare_configuration(ordinary_request, snapshot=None, initialized=False)
assert not result.ready
assert not result.ask_user
assert result.questions == []
```

## Task 2: Freeze confirmed sourcing values and share round usage

**Files:** schemas/sourcing.py, rules/registry.py, rules/bindings.py, storage/sourcing_repository.py, storage/read_repository.py, cli/sourcing.py, cli/jobs.py and sourcing integration tests.

**Interfaces:** SourcingRunRequest adds top_per_query, rules_version and base_rules_version. bind_sourcing_run(rules, request, source_ceiling) returns a validated frozen request. ReadReservation optionally binds a run_id and candidate. Query and detail reservations validate the candidate's current head and initialization before new operations.

- [x] Write failing tests proving a dynamic round consumes exact configured values, explicit mismatches reject, the source profile never expands automatically, a missing initialization blocks and stale rounds cannot reserve.
- [x] Write failing mixed-entry tests: a failed detail read plus a bound capture exhaust the same round; replay does not reauthorize; daily usage and halts remain shared; an unbound capture cannot bypass an initialized profile.
- [x] Move TOP_PER_QUERY and DETAIL_ATTEMPTS_PER_SITE_PER_ROUND to runtime definitions with exact consumers and no defaults.
- [x] Fill omitted request values from the confirmed snapshot; reject conflicting explicitly provided values. Preserve the requested policy profile and source constraints.
- [x] Count bound capture attempts together with normal round detail attempts in the same atomic transaction. Keep actual result recording possible after a rule change so already incurred costs and risk observations are not lost.
- [x] Support explicitly owner-approved round-only snapshots without replacing the reusable head; bind them to one run and base head. Reject wrong-run reuse and persistent promotion.
- [x] Run focused tests and check old sourcing behavior remains compatible when no configured profile exists.

Test boundary:

```python
assert frozen.top_per_query == confirmed.values["TOP_PER_QUERY"]
assert frozen.detail_limit == confirmed.values["DETAIL_ATTEMPTS_PER_SITE_PER_ROUND"]
assert not replay.allowed
assert next_detail.reason == "round_detail_limit"
```

## Task 3: Real query-result consumer and replay protection

**Files:** sourcing query contracts, pure jobs/query_selection.py, storage/query_repository.py, migration0032, cli/sourcing.py and the listings adapter in cli/jobs.py, corresponding tests.

**Interfaces:** SourcingQueryCapture(attempt_id, items, loaded, access_state, next_cursor). SourcingQuerySelection returns requested count, observed/taken counts, input shortfall, exact duplicate IDs, selected items, rule version and cursor. SqliteQueryRepository.take(capture, now) persists immutable results and seen source IDs. Claiming an actual CLI query is atomic and one-time; unresolved outcomes require intervention rather than another external call.

- [x] Write failing tests for exact configured top count, fewer results with requested/shortfall, same-source exact-ID dedup across queries, false empty/loading/gate views, conflicting replay and concurrent claim rejection.
- [x] Implement pure selection over the first requested rows. Never semantically merge distinct platform IDs or fill missing input with invented rows.
- [x] Atomically record query selection, seen source IDs and successful query result. Preparation and plan generation write none of these tables.
- [x] Add jobs sourcing-take for host-captured results and wire jobs listings --run-id/--attempt-id/--database to the same consumer. A replay returns the recorded selection without executing the connector again. A provider gate records the actual failure and halts the source; never automatically retry.
- [x] Ordinary configured profiles cannot use an unbound legacy listing or detail route to evade the frozen values.
- [x] Run focused query and CLI regressions, using only injected fake connectors.

Test boundary:

```python
assert selection.requested == frozen.top_per_query
assert selection.shortfall == max(selection.requested - selection.taken_count, 0)
assert len({item.source_job_id for item in selection.items}) == len(selection.items)
assert connector_calls_after_replay == connector_calls_before_replay
```

## Task 4: Host protocols and verification

**Files:** AGENTS.md, hosts/personal-ai, SKILL.md, dynamic-variables.md, capability-catalog.md, CHANGELOG.md, approved design status.

- [x] State configure once, load thereafter, change only on explicit owner request. Keep ordinary missing/conflicting configuration non-interactive.
- [x] Document the preparation and initialization commands, exact consumers and scope limitations, actual owner evidence and private storage.
- [x] Update the capability catalog for the three new CLI commands and preserve all unrelated capabilities.
- [x] Run full pytest, Ruff, strict mypy and diff checks in order. Inspect privacy findings and preserve intentional synthetic negative fixtures.
- [x] Record final evidence and explicit limitations privately, without modifying live state or making unrequested commits/pushes.

## Baseline

1656 tests passed in 442.81 seconds before implementation. Existing approved design is present as an untracked document and will be preserved.

## Verified result

All four tasks are complete. The full suite passed with 1720 tests in 440.46 seconds; Ruff, strict mypy (227 source files) and diff checks passed. The isolated synthetic CLI exercise verified first initialization, reuse across task types and restored sessions, exact sourcing values, one-time query execution, and consumed owner-request rejection. Public-text privacy scanning has no unresolved findings; existing synthetic negative fixtures are separately classified. Final evidence is kept under candidate/private/codex-harness/reviews/first-run-configuration-2026-10-30/. No live parameters, external actions, production database migration, scheduler changes, commits or pushes were performed. MCP orchestration and the production-pipeline conflict guard remain outside this feature.
