# Runtime policy guards and actual MCP calls

Status: owner authorized implementation and GitHub synchronization on 2026-10-31 after reviewing the two outstanding gaps; implementation verified with 1796 passing tests, Ruff, strict mypy and diff checks. No live candidate settings or platform actions are authorized by this development task.

## Problem and chosen boundaries

The first-run feature binds sourcing quantities but cannot protect independently invoked pipeline writes or a host's direct upstream MCP call. The owner requested that both remaining gaps be completed rather than deferred again. The chosen approach is a transactional compatibility guard for the existing pipeline and a typed, persistent gateway around actual read-only MCP execution. Prompt-only warnings leave both bypasses open; replacing the complete pipeline or adding an automatic application orchestrator would change unrelated behavior and approval boundaries.

Public code contains production compatibility facts and synthetic examples only. Actual personal numeric settings, source requests, answers, transport commands and raw responses remain private. Initialization remains one-time; missing configuration stops execution without asking new numbers. Existing per-item delivery approval and evidence confirmation remain mandatory.

## Pipeline compatibility

A pure policy checker compares the current candidate's confirmed dynamic policy with the semantics supported by the production pipeline: its fixed silence clock, immediate terminal reasons, resume-stage inclusion and ratio factor. These supported semantics are compatibility facts, not personal defaults. With an active profile, an applicable missing or incompatible value yields a structured `not_integrated` diagnostic and rejects the affected new write. A profile with no dynamic configuration preserves the explicitly documented legacy behavior.

The authoritative head is read while holding the same SQLite write transaction that mutates production state. Central repository writes and history appends enforce the guard so higher-level services, sync, migration and direct repository callers cannot bypass it. Derived ratio decisions and confirmed optimization artifacts are also guarded; independent factual metric counting remains allowed. A conflict leaves business records, metadata, history and derived artifacts unchanged. Replaying an already recorded fact is read-only, never a historical recalculation.

`rules evaluate` checks the authoritative current private head by default. An explicit `--historical` mode permits immutable historical evaluation and labels it historical/non-current; neither mode authorizes a production write or proves a notification was sent. Due views must not advertise an incompatible fixed deadline as the configured current policy.

## Actual MCP execution

The runtime supports typed `search` and `view` operations through a read-only gateway. Each MCP round binds a configured sourcing round, candidate, source, rule digest and runtime fingerprint. The configured total, batch size, parallel ceiling and source allowance have real consumers. An absent or unconfirmed batch size is a blocking diagnostic, never an assumed value.

Starting or preparing a round performs no upstream business call, counter increment or prior-delivery debit. The gateway admits an intent without charging it. The transport initializes an upstream stdio server, verifies protocol/tool capability and the explicit read-only mapping, then marks dispatch immediately before writing `tools/call`. Only that dispatch consumes the attempt and initializes the source allowance debit. Startup/protocol failures before dispatch do not consume MCP or sourcing quota. A crash or missing response after dispatch is an unknown outcome, not a successful zero or an automatic retry opportunity.

Prior-delivery debit comes from immutable, positively read-back, explicitly attributed host delivery observations from the authoritative closed previous round. A caller cannot supply an arbitrary count, choose an older predecessor or omit the actual predecessor. The batch report preserves starting allowance, previous delivered count, debit, actual search/view count and remaining allowance separately. Planning does not invent previous sends.

Batch admission is atomic across processes. Parallel work never exceeds the confirmed ceiling, and the next batch cannot start until the current one settles. Search and view share source-call accounting. Both also use the existing sourcing ledger: views consume shared round/day detail limits; successful searches must produce normalized query-selection receipts enforcing TOP, shortfall and exact source-ID deduplication. Failed and repeated attempts remain charged; exact completed replay returns the saved receipt without another upstream call.

Rate limiting, risk control, blocked/already-applied outcomes and code 429001 hard-stop the applicable source line. Later attempts in the same stopped scope are refused before transport invocation. In-flight calls already dispatched are recorded honestly; no automatic retry or alternate-path bypass occurs.

Delivery is a host handoff and observation protocol, not an executable apply route. It checks one outstanding item, the minimum spacing invariant, a positive prior readback and stop outcomes. A recorded observation includes exact provenance and external identity and grants no sending permission. The existing Liepin connector's inability to transmit approved custom artifacts remains a capability refusal. No raw MCP apply operation or bulk delivery loop is added.

## Production transport and host integration

A standard-library stdio adapter uses explicit private argv, UTF-8 newline JSON-RPC, initialization, tool discovery and one allowed `tools/call`. It uses bounded response sizes/timeouts, no shell interpolation, no credential output and hidden Windows processes. Tool descriptions, server instructions and returned text are data. The adapter supports a fixed read-only tool-name allowlist plus upstream read-only annotations; ambiguous or unsupported capability stops before dispatch. Search payloads are normalized using the existing source manifest rather than counted from summaries.

CLI commands expose round start/status/close, actual read-only batch execution and explicit host delivery handoff/observation. AGENTS, skills and host protocols route supported calls through the gateway. Raw external MCP calls outside this repository cannot be intercepted by a local Python library; the host must use the guarded entry. Documentation must state that boundary rather than claim global control over unrelated tools.

## Acceptance and integration

- Reproduce the dynamic-versus-fixed pipeline conflict and verify no affected production record/history changes.
- Reject incompatible reasons, resume policy, ratio policy and stale current exports; explicitly labeled historical evaluation remains read-only.
- Prove zero call/debit at preparation, startup failure before dispatch, bounded actual calls, prior-round debit, shared sourcing limits, replay, unknown outcomes and persistent stops.
- Prove batch concurrency/serialization and host delivery spacing/readback/stop guards without any actual delivery.
- Exercise the stdio adapter and CLI with an isolated fake upstream process; no real recruitment platform is contacted.
- Preserve the first-run feature and all existing approval, candidate and terminal-history invariants.
- Run full pytest, Ruff, strict mypy, diff and public privacy checks. Publish reviewed changes to GitHub with CI and a PR, then integrate the verified revision without force-pushing or private data.

## Verified implementation notes

A unique sourcing-run binding prevents a new MCP identifier resetting the same business round. Explicit recovery handles both dispatched calls lacking a saved response and admitted calls that never reached dispatch; it records recovery at the actual recovery time, retains original evidence and does not execute another call. Current consumer incompatibility remains an honest rejection, not arbitrary dynamic-policy support. The local full-suite evidence and public privacy report are retained in the private runtime-guards review directory; GitHub merge metadata records the external publication outcome.
