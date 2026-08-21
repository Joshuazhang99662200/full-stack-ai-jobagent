# Domain model

## Candidate and evidence

`CandidateProfile` describes who the candidate is. `EvidenceItem` records why the system may make a claim. Evidence keeps source, confidence, confirmation state, chronology, skills, domains, and metric facts. A resume is a projection over admissible evidence and is never the candidate source of truth.

Adaptive interview operates on explicit `CandidateGap` records. An answer creates draft evidence; the optimizer cannot answer a gap or confirm evidence.

## Jobs and intelligence

`NormalizedJob` preserves the full JD and all cross-source provenance. `JobRequirementProfile` decomposes requirements without depending on a connector. `HardFilterResult` represents deterministic `PASS`, `REVIEW`, or reasoned `REJECT`. `MatchResult` evaluates the candidate against the job and always includes explanation lanes.

The offline data flow is:

```text
SourceJobRecord
-> NormalizedJob
-> JobRequirementProfile
-> HardFilterResult
-> RequirementMatchSet
-> MatchResult
-> RankedJob
```

Normalization uses stable source-observation IDs. Deduplication may assign a canonical group ID, while retaining each source ID, URL, and collection timestamp in `provenance`. Conflicting source facts remain visible through warnings.

Hard filtering runs before evidence matching. `REJECT` records contain stable rule IDs and never enter the matcher. `REVIEW` records may be matched for decision support, while their status remains `REVIEW`. Ranking orders eligible assessments deterministically and leaves `application_ready` false.

`RequirementMatchSet` is a reviewed reasoning artifact. Its job ID, candidate ID, requirement coverage, and Evidence IDs are revalidated. Only confirmed, non-weak Evidence owned by the current Candidate can support or partially support a requirement. Missing Evidence creates a gap or uncertainty.

## Resume optimizer

`ResumeOptimizationPlan` maps requirements to evidence and allowed rewrite operations. `ResumeVariant` contains selected evidence, optimized items, a `ClaimLedger`, verification, keyword coverage, and diff. Every substantive `ClaimRecord` has at least one `EVID_*` ID.

`MatchResult` and `ResumeCompatibilityResult` answer different questions. The first measures whether the person fits the job; the second measures whether one resume variant presents the relevant supported evidence.

## Application lifecycle

`ApplicationPackage` is the review artifact. `ApprovalRecord` is immutable and binds approval to job, resume, message, and policy digests. If any digest changes, `ApprovalRecord.matches` returns false and delivery must fail with stale approval.

`DeliveryResult` records sent, failed, or intervention-required state. `ApplicationAudit` stores artifact IDs, digests, attempt number, outcome, and timestamp without duplicating private resume or message bodies.

Batch execution remains ordered and sequential. A compatibility proposal is not an approval and an approval is not a delivery command.
