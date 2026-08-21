# Job Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver an offline, deterministic-first Job Intelligence workflow that searches mock source records, normalizes and deduplicates jobs with full provenance, decomposes JDs through typed reasoning, performs deterministic hard filtering, produces evidence-grounded match results, ranks eligible jobs, persists artifacts in SQLite, and exposes JSON-first CLI commands.

**Architecture:** Read-only discovery, deterministic intelligence, structured reasoning, persistence, and CLI are separate layers. Safety-critical decisions and final score aggregation remain deterministic; provider output is revalidated against the exact job, requirement, and candidate Evidence IDs before use.

**Tech Stack:** Python 3.11+, Pydantic v2, stdlib `sqlite3`, provider-neutral `ReasoningProvider`, Typer, pytest, Ruff, mypy

## Global Constraints

- `JobSource != Job Intelligence`; the Phase 3 source port is read-only.
- `Search != Apply`; no Phase 3 code imports or invokes application delivery.
- `Hard Filter != Semantic Match`; filtering always precedes matching in the pipeline.
- `Candidate-Job Match != Resume-Job Compatibility`.
- `REVIEW` is never automatically promoted to `PASS`.
- A `REJECT` result includes at least one stable rule ID and explanation.
- Supported matches cite only confirmed, non-weak Evidence owned by the current Candidate.
- Missing Evidence becomes a gap or uncertainty and never a candidate fact.
- Deduplication preserves all source IDs, URLs, and observation timestamps.
- Thresholds live in typed policy contracts.
- Every production change follows red-green-refactor and ends in a focused commit.

---

## File Map

```text
src/jobagent/schemas/jobs.py                  Add warnings and merged provenance support
src/jobagent/schemas/job_intelligence.py      Source, dedupe, filter-context, mapping, ranking contracts
src/jobagent/jobs/ports.py                    Read-only discovery and job repository protocols
src/jobagent/connectors/mock.py               Fixture-backed MockJobSource
src/jobagent/connectors/fixtures/jobs.json    Public synthetic source jobs
src/jobagent/jobs/normalization.py            Canonical fields, salary, IDs, provenance
src/jobagent/jobs/deduplication.py            Exact/near duplicate grouping and merge
src/jobagent/storage/migrations/0002_jobs.sql Job Intelligence tables
src/jobagent/storage/job_repository.py        SQLite adapter
src/jobagent/reasoning/job_requirements.py    Structured JD decomposition adapter
src/jobagent/jobs/hard_filter.py              Deterministic rule engine
src/jobagent/reasoning/job_matcher.py         Structured requirement/evidence mapping adapter
src/jobagent/jobs/matching.py                 Admissibility and deterministic aggregation
src/jobagent/jobs/ranking.py                  Stable eligible-job ranking
src/jobagent/jobs/workflow.py                 Offline orchestration
src/jobagent/cli/jobs.py                      JSON-first Job commands
src/jobagent/cli/app.py                       Register jobs command group
tests/jobs/*                                  Domain and application tests
tests/connectors/*                            Mock source contract tests
tests/storage/test_job_repository.py          Migration and repository tests
tests/reasoning/*                             Provider-output boundary tests
tests/cli/test_jobs.py                        CLI tests
tests/workflows/test_job_intelligence.py      Offline vertical acceptance
```

### Task 1: Phase-specific Serialized Contracts

**Files:**
- Modify: `src/jobagent/schemas/jobs.py`
- Create: `src/jobagent/schemas/job_intelligence.py`
- Modify: `src/jobagent/schemas/__init__.py`
- Test: `tests/schemas/test_job_intelligence.py`

**Interfaces:**
- Produces `SourceJobRecord`, `JobSearchQuery`, `DeduplicationPolicy`, `DuplicateGroup`, `DeduplicationResult`, `CandidateFilterContext`, `HardFilterPolicy`, `RequirementMatchOutcome`, `RequirementEvidenceMatch`, `RequirementMatchSet`, `MatchThresholdPolicy`, `JobAssessment`, `RankedJob`, and `JobIntelligenceRun`.
- Adds `warnings: list[str]` to `NormalizedJob` without changing existing required fields.

- [ ] **Step 1: Write failing contract tests**

```python
def test_supported_requirement_mapping_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        RequirementEvidenceMatch(
            requirement_id="REQ_001",
            outcome=RequirementMatchOutcome.SUPPORTED,
            evidence_ids=[],
            explanation="Candidate has the skill.",
        )


def test_ranked_review_job_cannot_be_application_ready() -> None:
    with pytest.raises(ValidationError):
        RankedJob(
            job_id="JOB_001",
            rank=1,
            filter_decision=FilterDecision.REVIEW,
            match_decision=MatchDecision.STRONG_MATCH,
            overall=0.9,
            application_ready=True,
            explanation="Location requires review.",
        )
```

- [ ] **Step 2: Run `python -m pytest tests/schemas/test_job_intelligence.py -q` and confirm missing imports.**
- [ ] **Step 3: Implement strict Pydantic contracts and cross-field validators.** `RequirementMatchSet` requires unique requirement IDs and matching `job_id`/`candidate_id`; `RankedJob.application_ready` must be false in Phase 3 and for non-PASS filters.
- [ ] **Step 4: Re-run focused tests, Ruff, and mypy.**
- [ ] **Step 5: Commit with `feat: add job intelligence contracts`.**

### Task 2: Read-only Mock Job Discovery

**Files:**
- Create: `src/jobagent/jobs/__init__.py`
- Create: `src/jobagent/jobs/ports.py`
- Create: `src/jobagent/connectors/__init__.py`
- Create: `src/jobagent/connectors/mock.py`
- Create: `src/jobagent/connectors/fixtures/jobs.json`
- Test: `tests/connectors/test_mock_job_source.py`

**Interfaces:**
- Produces `JobDiscoverySource.search(query: JobSearchQuery) -> list[SourceJobRecord]`, `fetch_job(source_job_id: str) -> SourceJobRecord`, and `get_recruiter(source_job_id: str) -> RecruiterInfo | None`.
- `MockJobSource.from_path(path: Path)` loads strict fixture JSON once and returns stable source-ID ordering.

- [ ] **Step 1: Write failing tests for token search, equality filters, stable order, fetch, recruiter, unknown source ID, and absence of preview/submit methods.**
- [ ] **Step 2: Confirm the missing connector failure.**
- [ ] **Step 3: Add at least four synthetic fixture records, including two cross-source duplicates and one distinct role. Implement case-insensitive AND token matching and exact optional filters.**
- [ ] **Step 4: Run connector tests and assert `not hasattr(source, "submit_application")`.**
- [ ] **Step 5: Commit with `feat: add read-only mock job discovery`.**

### Task 3: Deterministic Job Normalization

**Files:**
- Create: `src/jobagent/jobs/normalization.py`
- Modify: `src/jobagent/errors.py`
- Test: `tests/jobs/test_normalization.py`

**Interfaces:**
- Produces `JobNormalizer.normalize(record: SourceJobRecord) -> NormalizedJob`.
- Adds `JobNotFoundError(code="JOB_NOT_FOUND")` and `JobNormalizationError(code="NORMALIZATION_ERROR")`.

- [ ] **Step 1: Write failing tests for Unicode/whitespace normalization, deterministic IDs, salary parsing, provenance, ambiguous salary warnings, and empty required fields.**
- [ ] **Step 2: Confirm the missing normalizer failure.**
- [ ] **Step 3: Implement NFKC normalization and `JOB_{SHA256[:16].upper()}` source-observation IDs. Parse only unambiguous `<currency> <min>-<max> <period>` salary text; otherwise retain a warning and `salary=None`.**
- [ ] **Step 4: Run focused tests, Ruff, and mypy.**
- [ ] **Step 5: Commit with `feat: normalize source jobs deterministically`.**

### Task 4: Provenance-preserving Deduplication

**Files:**
- Create: `src/jobagent/jobs/deduplication.py`
- Test: `tests/jobs/test_deduplication.py`

**Interfaces:**
- Produces `JobDeduplicator.deduplicate(jobs: Sequence[NormalizedJob], policy: DeduplicationPolicy) -> DeduplicationResult`.
- Exact identity uses normalized company/title/location and JD digest. Near identity uses compatible location plus JD token Jaccard similarity.

- [ ] **Step 1: Write failing tests for exact merge, near merge, below-threshold separation, complete provenance, conflict warnings, input-order invariance, and idempotence.**
- [ ] **Step 2: Confirm the missing deduplicator failure.**
- [ ] **Step 3: Implement deterministic union/grouping, canonical `JOB_*` group IDs, canonical field selection, unique sorted provenance, and stable output ordering.**
- [ ] **Step 4: Run focused tests and repeat them with reversed inputs.**
- [ ] **Step 5: Commit with `feat: deduplicate jobs without losing provenance`.**

### Task 5: Job SQLite Migration and Repository

**Files:**
- Create: `src/jobagent/storage/migrations/0002_jobs.sql`
- Modify: `src/jobagent/storage/database.py`
- Create: `src/jobagent/storage/job_repository.py`
- Modify: `src/jobagent/jobs/ports.py`
- Test: `tests/storage/test_job_repository.py`

**Interfaces:**
- Upgrades schema version from 1 to 2 without recreating Candidate tables.
- Produces repository methods `save_job`, `get_job`, `list_jobs`, `save_requirements`, `get_requirements`, `save_filter_result`, `get_filter_result`, `save_match`, and `get_match`.
- `save_job` persists job JSON and relational provenance in one transaction.

- [ ] **Step 1: Write failing migration tests proving v1→v2 upgrade, idempotence, and Candidate data preservation.**
- [ ] **Step 2: Write failing repository round-trip, provenance, candidate isolation, digest-key, and rollback tests.**
- [ ] **Step 3: Change `Database.migrate()` to apply ordered migrations from current version through version 2. Implement parameterized repository SQL and Pydantic JSON round trips.**
- [ ] **Step 4: Run all storage tests and mypy.**
- [ ] **Step 5: Commit with `feat: persist job intelligence artifacts`.**

### Task 6: Structured Requirement Extraction

**Files:**
- Create: `src/jobagent/reasoning/job_requirements.py`
- Test: `tests/reasoning/test_job_requirements.py`

**Interfaces:**
- Produces `ReasoningJobRequirementExtractor.extract(job: NormalizedJob) -> JobRequirementProfile` using prompt ID `job.requirements.extract.v1`.

- [ ] **Step 1: Write fake-provider tests capturing minimum context and returning a valid profile. Add adversarial outputs for foreign job ID, duplicate requirement IDs, fake source spans, and aggregate-only statements.**
- [ ] **Step 2: Confirm the missing adapter failure.**
- [ ] **Step 3: Revalidate via `model_dump` → `model_validate`, normalize whitespace for source-span checks, and raise `InvalidProviderOutputError` with job ID and prompt ID only.**
- [ ] **Step 4: Run focused tests, Ruff, and mypy.**
- [ ] **Step 5: Commit with `feat: extract typed job requirements`.**

### Task 7: Deterministic Hard-filter Engine

**Files:**
- Create: `src/jobagent/jobs/hard_filter.py`
- Test: `tests/jobs/test_hard_filter.py`

**Interfaces:**
- Produces `HardFilterEngine.evaluate(job, requirements, context, policy) -> HardFilterResult`.
- Stable rules: `LOCATION_HARD_CONSTRAINT`, `WORK_AUTHORIZATION`, `LANGUAGE_HARD_REQUIREMENT`, `EDUCATION_HARD_REQUIREMENT`, `COMPENSATION_MINIMUM`, and `ROLE_EXCLUSION`.

- [ ] **Step 1: Add table-driven failing tests for PASS, explicit REJECT, unknown-data REVIEW, ambiguous comparison REVIEW, multiple reasons, and evaluation-order stability.**
- [ ] **Step 2: Confirm the missing engine failure.**
- [ ] **Step 3: Implement each rule as a pure function returning `FilterReason | None` plus decision severity. Aggregate `REJECT > REVIEW > PASS` and retain every triggered reason.**
- [ ] **Step 4: Run focused tests and confirm a valid rejection is returned rather than raised.**
- [ ] **Step 5: Commit with `feat: add deterministic job hard filters`.**

### Task 8: Evidence Admissibility and Reasoning Match Boundary

**Files:**
- Create: `src/jobagent/reasoning/job_matcher.py`
- Create: `src/jobagent/jobs/matching.py`
- Test: `tests/reasoning/test_job_matcher.py`
- Test: `tests/jobs/test_matching.py`

**Interfaces:**
- Produces `ReasoningJobMatcher.map(job, requirements, candidate_id, evidence) -> RequirementMatchSet` using prompt ID `job.match.evidence.v1`.
- Produces `MatchAggregator.aggregate(requirements, mappings, admissible_evidence, policy) -> MatchResult`.

- [ ] **Step 1: Write failing admissibility tests proving confirmed explicit/inferred Evidence may support, while weak or unconfirmed Evidence may only produce uncertainty.**
- [ ] **Step 2: Write adversarial fake-provider tests for foreign Candidate ID, unknown requirement ID, foreign Evidence ID, supported-without-evidence, and weak-only support.**
- [ ] **Step 3: Implement the structured adapter and reject invalid mappings before aggregation.**
- [ ] **Step 4: Implement deterministic dimension coverage, hard gaps for missing MUST requirements, threshold decisions, explanatory lanes, and unique cited Evidence IDs.**
- [ ] **Step 5: Add the acceptance regression: no confirmed RAG Evidence prevents `SUPPORTED` for a RAG requirement.**
- [ ] **Step 6: Run focused tests, Ruff, and mypy.**
- [ ] **Step 7: Commit with `feat: match jobs using admissible evidence`.**

### Task 9: Stable Job Ranking

**Files:**
- Create: `src/jobagent/jobs/ranking.py`
- Test: `tests/jobs/test_ranking.py`

**Interfaces:**
- Produces `JobRanker.rank(assessments: Sequence[JobAssessment], *, include_rejected: bool = False) -> list[RankedJob]`. `JobAssessment` contains job ID, `HardFilterResult`, `MatchResult`, publication timestamp, and must-have score.

- [ ] **Step 1: Write failing tests for PASS-before-REVIEW, rejected exclusion, decision tier, score, must-have, publication time, job-ID tie-break, and input-order invariance.**
- [ ] **Step 2: Confirm missing ranker failure.**
- [ ] **Step 3: Implement one explicit sort key and assign 1-based ranks after sorting. Keep `application_ready=False` for every result in Phase 3.**
- [ ] **Step 4: Run focused tests.**
- [ ] **Step 5: Commit with `feat: rank explainable job matches`.**

### Task 10: Offline Job Intelligence Workflow

**Files:**
- Create: `src/jobagent/jobs/workflow.py`
- Test: `tests/jobs/test_workflow.py`

**Interfaces:**
- Produces `JobIntelligenceWorkflow.run(query, candidate_id, filter_context, policies) -> JobIntelligenceRun`.
- Dependencies are injected: discovery source, normalizer, deduplicator, requirement extractor, hard filter, matcher, aggregator, ranker, repositories.

- [ ] **Step 1: Write a failing orchestration test with fake reasoning and real deterministic components.**
- [ ] **Step 2: Assert search/fetch failures create no partial match records and REJECT jobs never reach the matcher.**
- [ ] **Step 3: Implement explicit stage ordering and atomic per-artifact repository writes.**
- [ ] **Step 4: Run focused tests.**
- [ ] **Step 5: Commit with `feat: orchestrate offline job intelligence`.**

### Task 11: JSON-first Jobs CLI

**Files:**
- Create: `src/jobagent/cli/jobs.py`
- Modify: `src/jobagent/cli/app.py`
- Test: `tests/cli/test_jobs.py`

**Interfaces:**
- Adds `jobagent jobs search`, `fetch`, `normalize`, `dedupe`, `requirements`, `filter`, `match`, `rank`, and `pipeline`.
- Provider-dependent commands accept reviewed `JobRequirementProfile` or `RequirementMatchSet` JSON files when no production provider is configured.

- [ ] **Step 1: Write failing Typer tests using fixture source, temporary SQLite, and reviewed reasoning-output JSON.**
- [ ] **Step 2: Implement thin commands that emit contract JSON and structured errors without echoing candidate Evidence statements by default.**
- [ ] **Step 3: Assert CLI help contains no apply, approve, preview, send, or browser commands.**
- [ ] **Step 4: Run CLI tests and installed `jobagent jobs --help`.**
- [ ] **Step 5: Commit with `feat: expose job intelligence cli`.**

### Task 12: Offline Vertical Acceptance and Context Documentation

**Files:**
- Create: `tests/workflows/test_job_intelligence.py`
- Modify: `README.md`
- Modify: `docs/domain-model.md`
- Modify: `skills/job-hunting/references/job-intelligence.md`
- Modify: `skills/job-hunting/references/connector-contract.md`

**Acceptance flow:**

```text
MockJobSource search
-> normalize four observations
-> merge two duplicates with both provenance records
-> typed requirement extraction
-> deterministic PASS / REVIEW / REJECT
-> confirmed Candidate Evidence retrieval
-> typed requirement mappings
-> evidence-grounded MatchResult
-> stable RankedJob list
-> SQLite round trip
```

- [ ] **Step 1: Write the failing vertical test and required acceptance assertions from the approved design.**
- [ ] **Step 2: Implement only missing integration glue.**
- [ ] **Step 3: Document exact CLI examples, read-only boundary, provenance policy, Evidence admissibility, and REVIEW handling.**
- [ ] **Step 4: Run workflow, documentation, and Skill validation tests.**
- [ ] **Step 5: Commit with `test: complete job intelligence workflow`.**

### Task 13: Phase Quality Gate

- [ ] **Step 1:** Run `python -m pytest -q`; expected zero failures.
- [ ] **Step 2:** Run `python -m ruff check .`; expected no diagnostics.
- [ ] **Step 3:** Run `python -m ruff format --check .`; expected all files formatted.
- [ ] **Step 4:** Run `python -m mypy src`; expected success under strict mode.
- [ ] **Step 5:** Run the JobAgent Skill quick validator; expected valid.
- [ ] **Step 6:** Run `jobagent jobs --help` and confirm no delivery command.
- [ ] **Step 7:** Inspect `git status --short --ignored`; confirm fixtures are synthetic and no private Candidate, SQLite, credential, browser, or provider payload is tracked.
- [ ] **Step 8:** Review every Global Constraint above against tests and implemented imports.
- [ ] **Step 9:** Commit verification-only corrections as `test: complete job intelligence quality gate`; do not create an empty commit.

## Plan Self-review Result

- Spec coverage: discovery, normalization, deduplication, persistence, requirement extraction, hard filter, evidence matching, ranking, CLI, workflow, documentation, and quality gate are represented.
- Scope remains one subsystem: read-only Job Intelligence. Real connectors, optimizer drafting, preview, approval, and delivery remain excluded.
- Type consistency: `SourceJobRecord → NormalizedJob → JobRequirementProfile → HardFilterResult + RequirementMatchSet → MatchResult → RankedJob` is stable across tasks.
- Safety consistency: no task adds application mutation; REJECT is a result, REVIEW remains review, and unsupported Evidence cannot create a supported match.
- Placeholder scan: no deferred implementation markers or undefined neighboring interfaces remain.
