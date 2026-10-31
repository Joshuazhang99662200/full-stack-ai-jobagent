# Runtime Guards Implementation Plan

> **For agentic workers:** Use executing-plans and its explicit parallel-agent guidance. Root owns integration, transport, CLI, documentation, release and GitHub. pipeline_guard owns pipeline policy and evaluate semantics. mcp_gateway owns gateway contracts, accounting, migration0033 and execution service. Test first, preserve prior uncommitted first-run work, and do not commit or push from child agents.

**Goal:** Close the production pipeline conflict-write gap and the actual-call MCP accounting/execution gap, then publish the complete verified change to GitHub.

**Architecture:** Authoritative schemas and pure policy logic feed transaction-bound SQLite guards. A versioned MCP round shares sourcing receipts and calls a bounded read-only stdio transport through a dispatch callback. No new automatic delivery capability is introduced.

**Tech Stack:** Python standard library, Pydantic, SQLite, Typer, pytest, Ruff and strict mypy.

## Global constraints

- No real candidate configuration, platform call, delivery, scheduling or production database migration during development.
- Initialization remains once-only; only explicit owner requests reopen configuration.
- Existing approval/evidence and immutable terminal-history boundaries remain mandatory.
- All active consumer values must be confirmed, current and compatible; no silently substituted defaults or guessed batch size.
- MCP startup/initialization is not a counted business invocation. Post-dispatch uncertainty is retained and blocks automatic retries.
- A raw external MCP call outside the gateway cannot be claimed as intercepted. Supported host workflows use the guarded entry.

## Task 1: Pipeline production write guard

Files: new schemas/pipeline_policy.py, rules/pipeline_policy.py, storage/pipeline_policy.py; existing pipeline repositories/services/metrics/rules and CLI evaluate; focused rules/storage/CLI tests.

Interfaces: a pure compatibility result references the candidate and rule digest; `require_pipeline_policy(connection, candidate_id, consumer, now)` checks the authoritative head under the caller's write lock. Central production writes invoke it. `rules evaluate --database` verifies current head, while `--historical` labels a historical result.

- [x] Write and run red tests: a synthetic confirmed policy differing from production must not expire a record or append history; direct repository writes cannot bypass; partial active profiles fail closed.
- [x] Implement compatibility checks for silence duration, immediate reasons and resume stages; guard central writes/history, due views and affected service paths in the same transaction.
- [x] Write and run red tests for ratio-derived decisions and stale current exports, then implement ratio/rule-write guards and explicit historical evaluation.
- [x] Run focused pipeline, metrics, dynamic CLI and prior-feature regressions; inspect every changed path for unguarded production writes.

## Task 2: Actual-call MCP gateway and immutable ledger

Files: new schemas/mcp_calls.py, jobs/mcp_calls.py, storage/mcp_repository.py, connectors/mcp_gateway.py, migration0033_mcp_calls.sql; targeted query_repository connection-taking receipt helper; focused tests.

Interfaces: `McpRoundRequest` binds sourcing_run_id/candidate/source/version/predecessor. `McpCallRequest` binds call_id/run/batch/search-or-view/actual target. `McpProviderResult` carries actual status and normalized listings for a successful search. `McpReadGateway(repository, runner, clock).execute_batch(requests)` uses a runner `(request, mark_dispatched) -> result`.

- [x] Write and observe red tests for zero preparation usage, pre-dispatch failure, first-call prior-delivery debit, unknown/replay behavior and stale/missing configuration.
- [x] Implement append-only round/call/result and host delivery evidence. Read previous delivery count from the authoritative closed predecessor, never from a caller-supplied number.
- [x] Write and observe red tests for total/parallel/batch ceilings, serial batches, persistent 429001 stops and cross-process admission; then implement the atomic checks and bounded runner orchestration.
- [x] Bind actual search/view dispatch to existing sourcing attempt and query-selection receipts. Test combined entry-point detail/day limits and exact TOP/dedup/shortfall results.
- [x] Test serial delivery handoff, minimum spacing, positive prior readback and hard stops. Keep raw apply and unsupported approved-artifact transmission unavailable.

## Task 3: Executable stdio transport, CLI and shared registration

Files: new schemas/mcp_transport.py, connectors/mcp_stdio.py, cli/mcp_calls.py; connectors/cli_source.py pure payload parser; cli/app.py, rules/registry.py, storage/database.py and migration-version tests; new transport/CLI tests.

Interfaces: `McpStdioConfig` contains private explicit argv, read-only search/view mapping and bounded time/response limits. `StdioMcpRunner(config, source)` implements the gateway runner, marking dispatch only after initialization and read-only tool validation. `CliListingSource.parse_listings(payload, collected_at)` normalizes already-observed search data without executing a process.

- [x] Write failing parser/transport tests for initialization, unsupported tool, pre-dispatch startup failure, actual tool dispatch, business error, invalid/unknown output and a real isolated fake stdio server.
- [x] Implement the bounded UTF-8 JSON-RPC adapter and source-manifest normalization; reject mutation tools and untrusted server instructions as operation control.
- [x] Register the MCP CLI group, migration0033 and actual registry consumers. Add explicit current-snapshot/private-path validation and synthetic CLI regressions.
- [x] Keep all source and host data private; expose actual usage, stop state, version, query receipt and recovery information in results.

## Task 4: Documentation, release and GitHub

Files: AGENTS.md, skill/host startup and execution references, capability catalog, pipeline/dynamic/MCP protocol docs, CHANGELOG, package version and README.

- [x] Document supported guarded entry points and remaining capability refusals, preserving once-only initialization and human approval.
- [x] Update exact capability command catalog and release metadata. Existing first-run work is included rather than discarded.
- [x] Run full pytest, Ruff, strict mypy and diff checks in order. Run isolated synthetic integration and privacy scans; save detailed evidence privately.
Publication follows this verified implementation commit: stage only the reviewed public paths, commit the related runtime enforcement change, push the branch, create/attach a PR, inspect available checks, integrate the verified revision and read back GitHub/local state. The PR merge metadata and private verification record are authoritative for this external operation; this source document does not invent a future merge receipt.

## Baseline evidence

Before this implementation, `python -m pytest -q --basetemp candidate/private/t-close-baseline` passed all 1720 tests in 497.23 seconds. The existing first-run feature remains uncommitted on codex/first-run-configuration and will be preserved in this publication.

## Verification

1796 tests passed in 520.21 seconds. Ruff, strict mypy (237 source files), and diff checks passed in order. The public-text privacy scan checked 656 files with no unresolved findings; six existing synthetic negative fixtures were separately reviewed. Tests used isolated SQLite files, injected runners and real local synthetic stdio subprocesses, never a recruitment platform. Recovery regressions cover missing post-dispatch receipts and admitted-but-undispatched process loss. A unique sourcing/MCP round binding prevents allowance reset by changing an MCP run ID. No repository CI workflow is present in this source tree; do not invent a remote CI pass.
