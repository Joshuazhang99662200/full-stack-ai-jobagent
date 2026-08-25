# 能力目录

每一项能力都具备类型化的输入与输出契约、显式错误、无隐藏副作用、独立测试,以及一个可直接从 Python 调用的边界。

状态含义:

- **已落地** —— 有 Python 服务与 CLI 命令,现在就能调用。
- **仅契约** —— 只有 Pydantic schema,没有服务、没有 CLI。**不要假装它可调用**;需要它时,产出经人工评审的类型化 JSON,并说明这一步尚未自动化。
- **未开始** —— 连 schema 都还没有。

## 候选人(Candidate)

| 能力 | 状态 | 入口 |
|---|---|---|
| `parse_resume` | 已落地 | `jobagent candidate ingest` · `PdfResumeParser.parse` |
| `update_profile` | 已落地 | `jobagent candidate import-draft`(整份草稿写入;暂无字段级编辑) |
| `detect_gaps` | 已落地 | `jobagent candidate status` · `GapDetector.detect` |
| `ask_question` | 已落地 | `jobagent candidate question` · `AdaptiveInterview.next_question` |
| `add_evidence` | 已落地 | `jobagent candidate answer` · `jobagent candidate confirm` |

## 职位情报(Jobs)

| 能力 | 状态 | 入口 |
|---|---|---|
| `suggest_queries` | 已落地 | `jobagent jobs suggest-queries`(从已确认证据确定性推导检索词) |
| `search` | 已落地 | `jobagent jobs search`(`--source mock` 合成 fixture,产出含 JD 的 `SourceJobRecord`) |
| `search_listings` | 已落地 | `jobagent jobs listings`(`--source liepin`,产出**不含 JD** 的 `JobListing`) |
| `fetch` | 已落地 | `jobagent jobs fetch` |
| `normalize` | 已落地 | `jobagent jobs normalize` |
| `dedupe` | 已落地 | `jobagent jobs dedupe` |
| `extract_requirements` | 已落地 | `jobagent jobs requirements`(消费经评审的 JSON) |
| `hard_filter` | 已落地 | `jobagent jobs filter` |
| `match` | 已落地 | `jobagent jobs match`(消费经评审的 JSON) |
| `rank` | 已落地 | `jobagent jobs rank` |
| 离线全流程编排 | 已落地 | `jobagent jobs pipeline` |

## 简历优化器(Resume)

| 能力 | 状态 | 入口 |
|---|---|---|
| 能力索引发现 | 已落地 | `jobagent optimizer capabilities`(只读 L0 元数据) |
| `retrieve_evidence` | 仅契约 | `RequirementEvidenceMapping` |
| `plan` | 仅契约 | `ResumeOptimizationPlan`、`SectionOptimizationPlan` |
| `tailor` | 仅契约 | `OptimizedResumeItem`、`RewriteOperation` |
| `verify` | 仅契约 | `ClaimLedger`、`VerificationReport`、`KeywordCoverageReport` |
| `diff` | 仅契约 | `ResumeDiff`、`ResumeDiffItem` |
| `render` | 未开始 | 无 schema;渲染约束见 [rendering-ats.md](rendering-ats.md) |

优化器索引中的八个 `repo.*` capability 条目指向的 Python 代码**确实已经存在**,但它们的 Phase 2 adapter 尚未落地,因此优化器路由器无法执行它们。索引条目是可发现的元数据,不是可调用的入口。

## 消息与投递(Message / Application / Cluster)

| 能力 | 状态 | 入口 |
|---|---|---|
| `generate`(消息) | 未开始 | 无 schema;策略见 [message-generation.md](message-generation.md) |
| `prepare` | 仅契约 | `ApplicationPackage` |
| `preview` | 仅契约 | `ApplicationPackage`(预览态) |
| `approve` | 仅契约 | `ApprovalRecord` |
| `send` | 仅契约 | `DeliveryRequest`、`DeliveryResult` |
| `audit` | 仅契约 | `ApplicationAudit`;策略见 [audit-feedback.md](audit-feedback.md) |
| `resume_compatibility` | 仅契约 | `ResumeCompatibilityResult`、`CompatibilityThresholds` |

投递链路(prepare → preview → approve → send → audit)目前**没有任何可执行代码**。不要为了"跑通流程"而在技能内部临时实现审批或投递;缺少这些能力时,按 [stop-conditions.md](stop-conditions.md) 停下来交给人。
