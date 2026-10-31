# First-run configuration and explicit owner changes

Status: approved by the owner; implemented and verified on 2026-10-30. No personal parameters are activated.

## Purpose

During first-time initialization, the agent prepares one configuration form and asks the owner to decide unresolved operating parameters, including per-query result count and per-source, per-round detail attempts. The confirmed profile is reusable until the owner explicitly requests a change. These values are private configuration inputs, not repository-wide defaults.

Subsequent rounds, different task types and restored sessions load that same confirmed profile without reopening the form or asking for the numbers again. A new task type, a missing field, an ambiguous value, a changed requirement or a conflict must not independently trigger another configuration conversation. Only first-time initialization and an explicit owner request to change configuration authorize that interaction.

The task remains in preparation until the required decisions and consumer checks are complete. Preparing a form must not search, open a job page, reserve a read, spend a quota, send a notification, or create a schedule.

## Options considered

1. **Typed initialization plus explicit owner changes (recommended):** the core distinguishes initial setup, ordinary execution and owner-requested changes. It returns configuration questions only for the first and third modes; ordinary execution returns a read-only plan or a blocking diagnostic. Existing confirmation/history contracts remain authoritative.
2. **Host instructions only:** add a startup checklist to AGENTS and host references. This improves prompting but cannot reliably reject missing decisions or prevent consumers from using different values.
3. **A separate web configuration wizard:** build a fixed UI and another configuration store. This adds an unnecessary application and risks a second source of truth. A Markdown form backed by typed JSON is sufficient.

## Initial profile and form

At initialization, the agent identifies the private candidate profile, intended workflow, actual sources, available consumers and fixed code revision. It loads any existing authoritative settings and their provenance before deciding whether initial setup is necessary. An already initialized profile must never be treated as new merely because a task, type, source or session changed. Keep initialization status with the private profile; incomplete or blocked execution is not permission to reset that status.

Prepare the initial form around the intended supported workflow rather than asking every unrelated variable in the registry. Later execution adapts its read-only plan to the task while retaining the confirmed configuration. A genuinely absent setting required by a later task is a blocking configuration issue, not an automatic new setup question.

For initial setup of a workflow that performs queries and detail reads, show:

| Owner-facing field | Variable or input | Meaning |
|---|---|---|
| Sources and search direction | Current candidate preferences and actual task request | Which sources and confirmed search terms the task will use |
| Queries per source in a round | QUERIES_PER_SITE_PER_ROUND | Number of combination queries, distinct from returned job count |
| Results per query | TOP_PER_QUERY | Maximum observed results to take from each actual query |
| Detail attempts per source in a round | DETAIL_ATTEMPTS_PER_SITE_PER_ROUND | Failed and repeated attempts still consume the round allowance |
| Daily detail allowance and remaining usage | DETAIL_CAP_PER_DAY and the shared sourcing ledger | Show the confirmed policy and actual remaining allowance separately |
| Reading method and stopping behavior | Task plan plus supported source capabilities | Prefer a supported panel when appropriate; preserve incomplete coverage and recovery information at a limit |

Each numeric item carries its unit, current confirmed value if any, provenance, proposed change if any, applicable constraint, consumer support and decision status. During authorized initialization or an owner-requested change, the form distinguishes **already confirmed**, **awaiting owner decision**, **conflicting** and **unsupported**. Ordinary execution reports missing configuration or conflicts without generating questions or silently replacing values with repository defaults.

During authorized initial setup or an owner-requested change, an agent may explain a suggested value and its rationale. Suggestions remain unconfirmed. It must not reopen parameter negotiation on its own during ordinary execution. External documents, examples, previous unrelated candidates and uncorrected host guesses cannot supply owner confirmation. The public specification and rules contain no personal numeric defaults.

Initial decisions establish the reusable profile. A current-round override is available only when the owner explicitly requests it and must not overwrite the reusable configuration. Resolve ambiguous scope within that owner-requested change conversation; do not ask about scope again on each ordinary task.

## Dialogue and confirmation

1. On first setup, prepare the form before the first sourcing operation, including any real-page acceptance read. Capability checks that require no sourcing operation may run first. If an existing initialized profile is found, load it and skip setup questions.
2. On later tasks, reuse confirmed values and bind them to the execution plan without requiring another configuration confirmation. Different rounds, task types and restored sessions do not authorize new configuration questions.
3. Only first-time initialization or an explicit owner request to change configuration opens a configuration dialogue. Ask concrete questions using workflow language, such as how many results to take from each query and how many detail attempts to allow per source in a round. Explain the applicable allowance and supported policy so the owner can decide.
4. Keep a single form overview, but preserve the existing one-variable proposal and exact-question confirmation discipline. Persist each approved change serially against the current version; do not activate several stale proposals against one base version. An unanswered field, silence or a vague response cannot approve an unspecified number.
5. Read back the resulting private settings and prepare the final task plan. Parameter approval grants no permission to send a message, submit an application, modify an online resume or change a scheduler.
6. If an ordinary task encounters missing, ambiguous, incompatible or unsupported configuration, stop the affected operation and report its cause. Do not reopen a form, ask for new numbers, request reconfirmation, mutate settings or fall back to defaults. A later explicit owner instruction can start a change conversation.

## Readiness and execution

The core distinguishes `initial_setup`, `ordinary_run` and `owner_requested_change`. `needs_user_decision` and configuration questions are permitted only in initial setup or an explicitly owner-requested change. Ordinary runs expose `blocked_by_missing_configuration`, `blocked_by_conflict`, `unsupported_consumer` or `ready`; a blocked ordinary run never promotes itself into setup or change mode. Only a compatible plan with all required values already confirmed may become ready.

The final plan binds the candidate, task identity, selected sources, code revision, configuration version, confirmed values and approved scope. It shows round limits and actual daily remaining usage without rewriting one into the other. If a daily allowance limits how much of the planned round can actually run, show that constraint explicitly and retain the configured round limit.

Starting or resuming work revalidates the authoritative configuration and plan without asking the owner to reconfirm unchanged settings. Changed values or constraints invalidate the affected plan and cause a diagnostic rather than another configuration prompt; do not silently adopt new values mid-round. Generating or displaying a plan does not reserve or consume quota.

The numeric values must reach the real consumers: TOP_PER_QUERY reaches the query-result boundary, and DETAIL_ATTEMPTS_PER_SITE_PER_ROUND reaches a versioned source round and its attempt reservations. A form alone is insufficient. Missing consumer support blocks the affected operation even when the owner has supplied a number. Do not mark a host-only variable as an implemented consumer merely because it appears on the form.

Source policy facts are verified constraints, not choices the owner can override by entering a larger number. A confirmed value that conflicts with a source ceiling, frozen round or production rule produces a conflict that prevents the affected operation. No silent fallback, clamping, policy expansion or historical-state recalculation is permitted.

## Implementation boundaries

- Keep preparation inputs and outputs in `src/jobagent/schemas/`; do not duplicate authoritative contracts in prompts or CLI modules.
- Add a pure preparation service for initialization mode, required fields, decision status, scope, compatibility and readiness. Its mode boundary must prevent ordinary tasks from producing configuration questions. It performs no storage, browser or platform operations.
- Add a thin CLI adapter that reads the private initialization status and current settings. It emits an initial or owner-requested change form only when authorized; ordinary runs emit a read-only plan or diagnostic. It does not fabricate owner decisions or invoke external actions.
- Reuse the existing private rule history and confirmation mechanisms. A prepared task plan is an execution binding, not another editable configuration authority.
- Bind the two numeric settings to existing sourcing consumers and make unsupported routes explicit. Preserve shared daily usage, intervention halts and per-item delivery approval.
- Add concise startup routing to AGENTS, SKILL and the personal-host references: configure once, load thereafter, change only at the owner's explicit request. These rules apply across task rounds and types and to every supported occupational role.
- Keep actual values, completed forms, owner answers and plans private. Public docs and tests use synthetic data only.

The first implementation focuses on preparation and the two sourcing quantities, with the already-supported query-count and daily-budget constraints shown in context. It does not implement MCP orchestration, platform delivery, online-resume changes, a web UI or a scheduler. The previously identified production-pipeline conflict guard remains a separately tracked defect; the preparation flow must not claim that defect is fixed or authorize unsupported production-state writes.

## Acceptance

- A first-time interactive initialization produces the relevant questions before any sourcing operation or quota consumption. An unconfigured background or ordinary task is blocked without opening a configuration conversation.
- An initialized profile is reused across later rounds, different task types and restored sessions without configuration questions or repeated confirmation.
- Only an explicit owner request reopens configuration after initialization; absent values, changed requirements, ambiguous fields, conflicts and unsupported consumers cannot trigger it automatically.
- A blocked ordinary run reports the relevant problem, preserves the confirmed profile and remains non-interactive until the owner explicitly requests a change.
- Initial confirmation persists reusable configuration; an explicitly requested current-round override remains separate and cannot leak into subsequent tasks.
- Result count and query count remain distinct, and every displayed numeric field has an explicit unit and scope.
- A host suggestion or an attached configuration table cannot activate a parameter.
- Confirmation changes only the named variable and intended scope; current-version conflicts preserve prior settings and history.
- A prepared plan becomes invalid if its candidate, rules, scope, code or source constraints change.
- Both sourcing quantities reach their actual consumers with the confirmed values. Failed and repeated detail attempts consume the same round and shared daily budget.
- A configuration accepted by the form but unsupported by a consumer remains blocked; no default can disguise the missing binding.
- First-run acceptance reads also obey preparation and budget requirements.
- Preparing, reviewing or approving parameters never sends, applies, schedules or claims successful notification.
- The startup form and tests remain role-neutral and contain no real candidate information.

## Review note

The implementation now provides typed preparation modes, private initialization records, explicit owner-request guards and actual query/detail consumers. Ordinary execution remains non-interactive across rounds, task types and restored sessions. A consumed owner message cannot reopen configuration by changing its timestamp, scope or run identity. Round-only approvals remain separate from the reusable head.

Verification: 1720 tests passed; Ruff, strict mypy (227 source files) and diff checks passed. An isolated synthetic CLI exercise covered first setup, initialization, subsequent reuse, one-time query execution and explicit owner changes. The public-text privacy scan found no unresolved findings; existing synthetic negative fixtures were reviewed separately. No live configuration, production database or external platform was changed. MCP orchestration and the previously identified production-pipeline conflict guard remain outside this implementation.

## Follow-up

The separately scoped MCP gateway and pipeline compatibility write guard were implemented in the 2026-10-31 runtime-guards design and verified together with this feature for version 0.4.0. See [the follow-up design](2026-10-31-runtime-guards-design.md). The earlier implementation boundary above describes the first delivery, not an outstanding claim about the follow-up.
