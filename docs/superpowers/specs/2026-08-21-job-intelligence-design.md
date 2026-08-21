# Deterministic-first Job Intelligence Design

**Status:** Approved approach, written-spec review pending  
**Date:** 2026-08-21  
**Scope:** Mock job acquisition, normalization, provenance-preserving deduplication, requirement decomposition, deterministic hard filtering, evidence-grounded matching, persistence, and local CLI  
**Out of scope:** real platform login or scraping, browser automation, application preview, approval, resume optimization, messaging, and delivery

## 1. Objective

Phase 3 delivers a complete offline Job Intelligence workflow. It turns fixture-backed source jobs into normalized, deduplicated, filtered, and evidence-explained match results using the Candidate Core delivered in Phase 2.

The design is deterministic-first. Stable rules handle fields, provenance, identity, deduplication, hard constraints, thresholds, and final score aggregation. A provider-neutral reasoning adapter handles natural-language JD decomposition and semantic evidence comparison where rules alone would lose important meaning.

## 2. Selected Approach

Three approaches were considered:

1. Deterministic-first hybrid: rules own safety-critical decisions and reproducible aggregation; structured reasoning owns language interpretation. This is selected.
2. Reasoning-first pipeline: faster to prototype but more difficult to reproduce, audit, and test without a production provider.
3. Rule-only pipeline: highly reproducible but too weak for implicit requirements, terminology variation, and evidence entailment.

The selected design remains fully runnable offline through `MockJobSource` and a fake reasoning provider. Adding a production reasoning adapter later must not change domain contracts or deterministic decision rules.

## 3. Architectural Invariants

```text
JobSource != Job Intelligence
Search != Apply
Hard Filter != Semantic Match
Candidate-Job Match != Resume-Job Compatibility
REVIEW != PASS
Missing Evidence != Candidate Capability
Deduplicated Job != Lost Provenance
```

Additional rules:

- `job.search`, `job.fetch`, `job.normalize`, `job.dedupe`, `job.hard_filter`, `job.match`, and `job.rank` remain independently callable.
- Search and fetch are read-only in Phase 3.
- A hard-filter rejection always carries at least one stable rule ID and explanation.
- Ambiguous or unavailable constraint data returns `REVIEW`; it is never silently treated as passing.
- Match output may cite only evidence belonging to the current candidate.
- Final matching uses confirmed, non-weak evidence by default. Policy may include explicit unconfirmed evidence only in an uncertainty lane, never as a supported strength.
- Missing evidence produces gaps or uncertainty; the matcher does not infer candidate facts.
- Cross-source deduplication preserves every source ID, URL, and observation timestamp.
- Thresholds are typed configuration, not prompt text or scattered numeric constants.

## 4. Package Boundaries

```text
src/jobagent/
├── connectors/mock.py             Fixture-backed read-only discovery adapter
├── jobs/normalization.py          Source record to NormalizedJob
├── jobs/deduplication.py          Deterministic identity and merge policy
├── jobs/requirements.py           Reasoning-backed requirement decomposition
├── jobs/hard_filter.py            Deterministic candidate/job constraint rules
├── jobs/matching.py               Evidence admissibility, reasoning, aggregation
├── jobs/ranking.py                Stable ordering over eligible match results
├── jobs/ports.py                  Source, repository, and reasoning-owned ports
├── jobs/workflow.py               Offline orchestration without delivery
├── config/job_policy.py           Filter and match threshold contracts
├── storage/migrations/0002_jobs.sql
├── storage/job_repository.py      SQLite adapter
└── cli/jobs.py                    Thin JSON-emitting commands
```

Domain and application modules import no browser, platform SDK, DOM selector, credential, or delivery type. The mock connector may use package fixture files but does not read Candidate Core records.

## 5. Source and Normalization Contracts

`jobs/ports.py` introduces the read-only `JobDiscoverySource` protocol with `search`, `fetch_job`, and `get_recruiter`. `MockJobSource` implements that protocol from local fixture records. Search supports deterministic equality and token filters over query, title, company, location, and source ID. Results have stable ordering.

The existing delivery-capable `JobSource` protocol remains unchanged and is not invoked in Phase 3. A later application phase may extend or wrap `MockJobSource` with preview and mock-submit behavior after approval contracts are in scope. This phase does not add placeholder delivery methods.

Source fixtures use `SourceJobRecord`, a provider-side schema containing the raw observed fields. `JobNormalizer.normalize(record)` creates a `NormalizedJob` with:

- a stable `JOB_*` ID derived from normalized company, title, location, and source identity;
- canonical whitespace and Unicode normalization;
- complete raw JD text;
- structured salary when unambiguous;
- recruiter data when present;
- one `ProvenanceRecord` for the source observation;
- source URL and observed timestamps.

Normalization refuses empty title, company, location, JD, source ID, or URL. It records parse warnings for ambiguous optional fields rather than inventing a value.

## 6. Provenance-preserving Deduplication

Deduplication proceeds in two layers:

1. Exact identity: normalized company, normalized title, normalized location, and identical source-independent JD digest.
2. Near duplicate: normalized company and title match, locations are compatible, and deterministic JD token similarity meets a configured threshold.

Near-duplicate results that do not reach the threshold remain separate. The first collected canonical record provides display fields; the merged record retains the most complete JD and all unique provenance entries. Conflicting salary, location, or recruiter observations add merge warnings and require review by downstream consumers.

The merger never discards source IDs or URLs. Merging the same inputs in any order produces the same canonical ID, fields, provenance order, and digest.

## 7. Requirement Decomposition

`ReasoningJobRequirementExtractor` invokes prompt ID `job.requirements.extract.v1` and requests a typed `JobRequirementProfile`. Context contains only the normalized job ID, title, company, location, and raw JD.

Post-validation requires:

- output `job_id` equals the input job;
- every requirement has a unique `REQ_*` ID;
- every requirement has a non-empty source span found in the original JD after whitespace normalization;
- requiredness is `MUST`, `PREFERRED`, `CONTEXT`, or `UNCERTAIN`;
- aggregate fields do not introduce statements absent from atomic requirements;
- provider output cannot change normalized job fields or invoke tools.

Invalid output returns `INVALID_PROVIDER_OUTPUT`. There is no fallback that guesses complex requirements from keywords. A deterministic fixture extractor is supplied for offline tests.

## 8. Deterministic Hard Filtering

`HardFilterPolicy` contains enabled rules and typed candidate preferences/constraints. Initial rule catalog:

| Rule ID | Input | REJECT condition | REVIEW condition |
|---|---|---|---|
| `LOCATION_HARD_CONSTRAINT` | candidate constraint, job location | explicit incompatible location | remote/hybrid meaning ambiguous |
| `WORK_AUTHORIZATION` | candidate constraint, JD requirement | explicit incompatibility | either side unknown |
| `LANGUAGE_HARD_REQUIREMENT` | confirmed candidate language evidence, must-have language | explicit unmet requirement | proficiency wording cannot be compared |
| `EDUCATION_HARD_REQUIREMENT` | confirmed education, must-have education | explicit unmet hard requirement | equivalence ambiguous |
| `COMPENSATION_MINIMUM` | candidate minimum, normalized salary | maximum below minimum | salary absent or period/currency incomparable |
| `ROLE_EXCLUSION` | candidate excluded roles, normalized title | explicit excluded role | title is ambiguous |

Rule evaluation order is stable. Any REJECT yields overall `REJECT`; otherwise any REVIEW yields `REVIEW`; otherwise `PASS`. All triggered reasons remain in the result. `REVIEW` can be resolved only by new data or an explicit human decision in a future phase; Phase 3 never promotes it automatically.

## 9. Evidence-grounded Matching

Matching has four steps:

1. Retrieve evidence owned by the candidate.
2. Partition it into admissible confirmed evidence, weak evidence, unconfirmed evidence, and conflicting evidence.
3. Ask `ReasoningJobMatcher` to map atomic requirements to candidate evidence using prompt ID `job.match.evidence.v1`.
4. Revalidate mappings and aggregate deterministic dimension and overall scores.

The reasoning output is a typed `RequirementMatchSet`. Each item includes requirement ID, outcome, cited evidence IDs, explanation, and uncertainty. Outcomes are `SUPPORTED`, `PARTIAL`, `MISSING`, or `UNCERTAIN`.

Post-validation rejects:

- unknown requirement IDs;
- evidence IDs not present in the current candidate repository result;
- strengths supported only by weak, unconfirmed, or conflicting evidence;
- `SUPPORTED` without at least one admissible evidence ID;
- claims about candidate capabilities that do not appear in cited evidence;
- provider-supplied overall scores or final decisions.

Deterministic aggregation computes dimension scores for must-have coverage, preferred coverage, responsibility evidence, skill evidence, domain relevance, and risk. `MatchThresholdPolicy` maps the overall score and hard-gap state to `STRONG_MATCH`, `POSSIBLE_MATCH`, `WEAK_MATCH`, or `NOT_A_MATCH`.

The final `MatchResult` always includes at least one explanatory lane and lists every cited evidence ID. A job with an unresolved hard-filter `REVIEW` may be matched for analysis, but ranking preserves its review state and cannot label it application-ready.

## 10. Ranking

`JobRanker.rank` accepts normalized jobs, hard-filter results, and match results. Ordering is deterministic:

1. filter eligibility: `PASS`, then `REVIEW`; `REJECT` is excluded by default;
2. match decision tier;
3. overall score descending;
4. must-have dimension descending;
5. publication time descending when present;
6. stable job ID ascending.

Ranking returns explanations and never triggers application preparation or delivery.

## 11. SQLite Persistence

Migration `0002_jobs.sql` adds:

- `normalized_jobs`;
- `job_requirements`;
- `hard_filter_results`;
- `job_matches`;
- `job_provenance`.

Serialized Pydantic contracts are stored with schema versions. Provenance has relational rows for cross-source queries and remains duplicated inside `NormalizedJob` JSON only as the canonical serialized contract. Writes that persist a job plus its provenance are atomic. Match records are keyed by candidate ID, job ID, evidence-set digest, requirement-profile digest, and policy digest so stale results can be detected later.

## 12. CLI Surface

Phase 3 adds JSON-first commands:

```text
jobagent jobs search
jobagent jobs fetch
jobagent jobs normalize
jobagent jobs dedupe
jobagent jobs requirements
jobagent jobs filter
jobagent jobs match
jobagent jobs rank
jobagent jobs pipeline
```

Commands accept an explicit local database and fixture path where applicable. Provider-backed commands accept injected application configuration; tests use a fake provider. No command sends an application or opens a browser.

## 13. Error Handling

Stable failures include:

- `JOB_NOT_FOUND` for an unknown mock source or stored job;
- `NORMALIZATION_ERROR` for invalid required source fields;
- `DEDUPLICATION_CONFLICT` when records cannot be merged safely;
- `INVALID_PROVIDER_OUTPUT` for requirement or matching contract violations;
- `MISSING_EVIDENCE` when a supported mapping has no admissible evidence;
- `STORAGE_ERROR` for SQLite failures.

A valid hard-constraint rejection is a `HardFilterResult(REJECT, reasons=...)`, not an exception. Invalid filter configuration returns `CONTRACT_VALIDATION_ERROR`.

No policy, evidence, ambiguity, or schema failure is retried with looser rules. Provider transport retries remain outside this phase and must be bounded by a later adapter.

## 14. Testing Strategy

Tests are layered:

- schema tests for source records, mappings, policies, and ranked results;
- connector contract tests for search/fetch/recruiter and no-side-effect behavior;
- normalization tests for stable IDs, whitespace, salary, and provenance;
- order-invariant deduplication tests with full provenance preservation;
- hard-filter table tests for PASS, REVIEW, REJECT, and multi-reason aggregation;
- requirement extractor adversarial tests for fake spans and foreign job IDs;
- matcher tests for foreign Evidence IDs, unconfirmed-only support, missing evidence, and deterministic aggregation;
- repository round-trip, isolation, transaction, and stale-digest tests;
- CLI tests for JSON output and absence of application commands;
- one offline workflow acceptance test using MockJobSource and fake reasoning.

Required acceptance cases:

1. Two equivalent jobs from different sources merge into one canonical job retaining both provenance records.
2. A deterministic hard constraint returns `REJECT` with a stable rule ID.
3. Ambiguous location or compensation returns `REVIEW` and remains review in ranking.
4. No confirmed RAG evidence prevents a supported RAG requirement match.
5. A provider citing another candidate's Evidence ID is rejected.
6. A bare overall score without explanation remains schema-invalid.
7. Search, match, and rank produce no application or delivery record.

## 15. Delivery Slices

1. Phase-specific schemas and typed policies.
2. MockJobSource and contract tests.
3. normalization and canonical identifiers.
4. provenance-preserving deduplication.
5. SQLite job migration and repository.
6. structured requirement extraction.
7. deterministic hard-filter engine.
8. evidence admissibility and structured requirement matching.
9. deterministic score aggregation and ranking.
10. thin Job CLI and offline pipeline acceptance.
11. documentation, Skill Context, and full quality gate.

Each slice follows red-green-refactor, has a focused commit, and ends without connector delivery, browser automation, optimizer drafting, or application approval behavior.
