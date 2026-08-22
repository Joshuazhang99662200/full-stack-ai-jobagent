# Optimizer contracts

The runtime source of truth is `jobagent.schemas.optimizer`. Load this index when an atomic capability needs to choose or validate an Optimizer artifact; do not copy these models into a prompt pack or plugin.

## Rewrite and planning

- `RewriteOperation` is the closed mutation vocabulary.
- `BaseResumeDocument` and `BaseResumeItem` identify the source resume surface.
- `RequirementEvidenceMapping`, `SectionOptimizationPlan`, and `ResumeOptimizationPlan` bind intended mutations to requirements and evidence before drafting.
- `OptimizedResumeItem` records the resulting item and its operations.

## Claims and verification

- `ClaimRecord` and `ClaimLedger` enumerate claims and their evidence support.
- `VerificationIssue`, `VerificationReport`, and `KeywordCoverageReport` carry typed verifier outcomes.

## Diff, variant, and compatibility

- `ResumeDiffItem` and `ResumeDiff` expose reviewable changes.
- `ResumeVariant` assembles the validated output without changing delivery authority.
- `CompatibilityThresholds` and `ResumeCompatibilityResult` assess whether a variant can be reused.

## Evidence boundary

Optimizer capabilities may create rewrite proposals and route new facts to Candidate Core `add_draft`. Only Candidate Core `confirm`, after explicit user confirmation, may promote an item to canonical Evidence. These contracts do not grant authority to mutate canonical Evidence or perform any downstream platform action.
