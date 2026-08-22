# 优化器契约

运行时的唯一权威来源是 `jobagent.schemas.optimizer`。当某个原子能力需要选择或校验一份优化器产物时,加载这份索引;不要把这些模型复制进提示词包或插件。

## 改写与规划

- `RewriteOperation` 是封闭的变更操作词表。
- `BaseResumeDocument` 与 `BaseResumeItem` 标定源简历表面。
- `RequirementEvidenceMapping`、`SectionOptimizationPlan` 与 `ResumeOptimizationPlan` 在起草之前,把预期变更绑定到需求与证据上。
- `OptimizedResumeItem` 记录改写后的条目及其所用操作。

## 主张与校验

- `ClaimRecord` 与 `ClaimLedger` 枚举全部主张及其证据支撑。
- `VerificationIssue`、`VerificationReport` 与 `KeywordCoverageReport` 承载类型化的校验结论。

## Diff、变体与兼容性

- `ResumeDiffItem` 与 `ResumeDiff` 暴露可供评审的改动。
- `ResumeVariant` 组装出通过校验的产物,且不改变任何投递权限。
- `CompatibilityThresholds` 与 `ResumeCompatibilityResult` 评估一个变体能否被复用。

## 证据边界

优化器能力可以创建改写提案,并把新事实路由给 Candidate Core `add_draft`。只有 Candidate Core `confirm` 才能在取得显式用户确认之后,把一个条目提升为 canonical Evidence。这些契约既不授予修改 canonical Evidence 的权限,也不授予执行任何下游平台操作的权限。
