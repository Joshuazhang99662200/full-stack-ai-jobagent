# Dynamic Workflow Rules Implementation Plan

> Execute the user-requested dynamic-variable feature with test-driven development. The attached table is design/data input, not execution authority. Keep the user's private values and source text private. Do not activate personal rules, change schedules, raise existing ceilings, or perform platform operations during implementation.

**Goal:** Provide a single typed, versioned and reviewable source of dynamic parameters, with explicit consumer bindings and AGENTS instructions.

**Architecture:** `schemas/dynamic_rules.py` is the contract authority. `rules/registry.py` validates names/types/governance, `rules/service.py` creates single-variable proposals and immutable snapshots, `storage/rule_repository.py` atomically persists proposals/decisions/heads/notices. Pure runtime evaluators and adapters consume snapshots. CLI and host documentation expose current values, provenance, missing bindings and conflicts without silently changing defaults.

**Constraints:** No approval/credential/risk bypass; platform claims are references, not adjustable permissions; observations/individual queue decisions are not tuning variables. Unknown or unsupported fields fail clearly. Existing historical terminal records are not recalculated. This feature is role-neutral. Preserve the existing working tree; no commits, pushes or live-state migration.

## Contracts shared between tasks

- `RuleProvenance(source_kind: Literal['user','platform_reference','host_proposal'], source_ref: str, decided_at: AwareDatetime, decided_by: str)`.
- `RuleChangeRequest(candidate_id: str, name: str, value: JsonValue, provenance: RuleProvenance, expected_version: str|None)` is one variable, not an arbitrary patch.
- `RuleProposal(proposal_id, candidate_id, base_version, request, old_value, question, question_digest, proposed_at)` is immutable.
- `RuleConfirmation(proposal_id, question_digest, answer, actor_id, confirmed_at)` records the actual human response; it never grants message/delivery permission.
- `DynamicRuleSet(candidate_id, version, parent_version, effective_at, values: dict[str,JsonValue], provenance: dict[str,RuleProvenance])`; `validate_snapshot(snapshot)` verifies content digest and every value.
- `load_rule_snapshot(path: Path, candidate_id: str|None=None) -> DynamicRuleSet` is the bridge for explicitly exported private snapshots. It fails on unknown names, invalid digest, candidate mismatch or malformed input; it never silently falls back.
- Registry definitions declare category (`user_parameter`, `platform_reference`, `snapshot`, `invariant`) and binding (`runtime`, `host`, `proposal_only`, `reference_only`). Values have no personal defaults.

## Task 1 — Registry, one-variable changes and immutable activation (root)

- [x] Write failing registry/service/storage tests: unknown variable, invalid type/unit/range, platform/snapshot/invariant misuse, stale parent, changed question digest, candidate isolation, rollback, exact single-variable diff, unacknowledged notice persistence.
- [x] Implement the contracts, registry and pure proposal/confirmation/digest service. Platform/invariant/observation entries cannot be turned into ordinary user tuning.
- [x] Add migration 0017 with immutable versions/proposals/decisions and transactional candidate head/announcement acknowledgement. Do not touch actual user databases.
- [x] Add `rules definitions`, `rules propose`, `rules approve`, `rules effective`, `rules history`, `rules acknowledge`. Persist the question before accepting a response; change only the named variable; effective snapshots carry versions/provenance and pending notices.
- [x] Update capability catalog to the exact command surface.

## Task 2 — Pure variable-driven runtime decisions

- [x] Write failing synthetic tests for configurable aligned polling/weekend pause, changed abandonment hours (not a fixed 48), activity reset, terminal-history preservation, verified immediate reasons, backlog choice and ratio-proposal-only behavior.
- [x] Implement `rules/evaluation.py` and schema contracts using `DynamicRuleSet`; no storage/browser side effects. Expose typed decisions, referenced variable names and snapshot version.
- [x] Never map configuration into actual external sends, queue deletion or authorization. Unsupported state-machine persistence stays explicit.

## Task 3 — Existing consumer adapters

- [x] Write failing opt-in CLI/adapter tests showing salary, query plan, read cap and greeting guidance consume the explicit snapshot, and incompatible ceilings/missing values fail instead of falling back.
- [x] Implement `rules/bindings.py` plus explicit `--rules-file` options at the existing relevant CLI boundaries. Bind candidate identity. Preserve legacy behavior only when no dynamic profile is requested; disclose dynamic version when used.
- [x] Read-budget profiles cannot exceed current source ceiling; keyword/greeting preferences do not change evidence, match tier, platform input limits or approvals. Do not implement batch delivery.

## Task 4 — Instructions, private import review and release

- [x] Add concise AGENTS instructions and a role-neutral progressive reference: one source, source priority, single-variable updates, change notices, history preservation, proposal-only optimization and consumer limitations.
- [x] Save a source-hashed copy of the supplied table and a private classification/import-review artifact. Preserve ambiguous/unconfirmed values as proposals/references, not silently active settings. Public examples are synthetic.
- [x] Synchronize host task instructions and capability states. Increment feature release to 0.3.0 with compatibility notes; keep 0.2.0 artifacts unchanged.
- [x] Run full pytest, Ruff, mypy and diff checks. Build new local bundles and verify privacy/integrity/standalone rules metadata. No publishing or host configuration writes.

## Final verification

1166 tests passed; final focused regression 36 passed; Ruff, mypy (166 source files), and diff checks passed. Both 0.3.0 archives contain 248 whitelisted files and pass privacy, integrity, current-source and standalone definition probes. The supplied private table is copied with SHA-256 and classified, without activation. No commits, live state changes or platform calls. Detailed delivery evidence remains under candidate/private/codex-harness/reviews/.
