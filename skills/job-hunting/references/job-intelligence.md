# Job intelligence

Use this context for sourcing, normalization, deduplication, JD decomposition, hard filters,
candidate-job matching, or ranking.

## Required stage order

1. Search through a read-only `JobDiscoverySource`.
2. Normalize every `SourceJobRecord` without discarding the complete JD.
3. Deduplicate equivalent observations and retain all provenance.
4. Extract atomic `JobRequirement` items with exact JD source spans.
5. Run deterministic hard filters.
6. Skip evidence matching for `REJECT` jobs.
7. Map each remaining requirement to Candidate Evidence.
8. Aggregate scores deterministically and rank eligible assessments.

Keep `HardFilterResult` separate from semantic matching. Return `PASS`, `REVIEW`, or
`REJECT`; every reject requires a stable rule ID and explanation. Preserve `REVIEW` through
ranking and leave every Phase 3 `RankedJob.application_ready` value false.

## Evidence boundary

Supported and partial mappings may cite only Evidence that:

- belongs to the current Candidate;
- is explicitly user-confirmed;
- has `explicit` or `inferred` confidence;
- overlaps the requirement semantics after structured validation.

Weak or unconfirmed Evidence can inform uncertainty, but cannot support a claim. Unknown
Evidence IDs, incomplete requirement coverage, foreign Candidate IDs, and source spans absent
from the JD invalidate the reviewed reasoning artifact.

Matching reports dimension scores, strengths, partial matches, hard gaps, uncertainties, and
Evidence IDs. A bare percentage is invalid. Treat candidate-job fit and resume compatibility
as separate contracts. Job Intelligence artifacts become input context for the optimizer;
they do not authorize CV claims or delivery.

## Local command routing

Use `jobagent jobs search|fetch|normalize|dedupe` for deterministic source work. With no
runtime provider configured, pass reviewed `JobRequirementProfile` and `RequirementMatchSet`
JSON to `requirements`, `filter`, and `match`. The `pipeline` command resolves reviewed files
as `JOB_ID.requirements.json` and `JOB_ID.matches.json` and persists results in local SQLite.
