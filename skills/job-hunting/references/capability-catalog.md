# 能力目录

每一项能力都具备类型化的输入与输出契约、显式错误、无隐藏副作用、独立测试,以及一个可直接从 Python 调用的边界。

状态含义:

- **已落地** —— 有 Python 服务与 CLI 命令,现在就能调用。
- **仅契约** —— 只有 Pydantic schema,没有服务、没有 CLI。**不要假装它可调用**;需要它时,产出经人工评审的类型化 JSON,并说明这一步尚未自动化。
- **未开始** —— 连 schema 都还没有。
- **委托外部技能** —— 本项目不实现,由一个外部 Agent Skill 承担;该技能是下游消费者,消费本项目已校验的产物,**不替代任何契约或门禁**。上游边界见 [oss/source-manifest.yaml](oss/source-manifest.yaml)。

## 候选人(Candidate)

| 能力 | 状态 | 入口 |
|---|---|---|
| `parse_resume` | 已落地 | `jobagent candidate ingest` · `PdfResumeParser.parse` |
| `extract_draft` | 已落地 | `jobagent candidate onboard`(默认 `--provider agent`,由调用方智能体产出,无需凭证;`--provider claude` 走 API。证据仍未确认) |
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
| `ingest_jd` | 已落地 | `jobagent jobs ingest-jd`(人工补 JD 正文,门控平台的唯一路径) |
| `fetch_jd` | 已落地 | `jobagent jobs fetch-jd`(读公开详情页,把 `JobListing` 补齐为 `SourceJobRecord`) |
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
| `render` 前的完整改写链路 | 已落地 | `optimizer tailor` → 智能体写回 → `optimizer assemble` |
| `retrieve_evidence` | 仅契约 | `RequirementEvidenceMapping` |
| `plan` | 仅契约 | `ResumeOptimizationPlan`、`SectionOptimizationPlan` |
| `tailor` | 已落地 | `jobagent optimizer tailor`(按路由视角发出改写请求)→ `jobagent optimizer assemble`(校验并组装变体) |
| `verify` | 已落地 | `ClaimVerifier`,在 `assemble` 内确定性执行;独立复核每条指标,不采信模型自评 |
| `diff` | 已落地 | `ResumeDiffBuilder`,在 `assemble` 内由基础简历与变体机械推导 |
| `render` | 委托外部技能 | 无本项目 schema;默认路由到 resume-builder(MIT)出 PDF,约束与边界见 [rendering-ats.md](rendering-ats.md) |

优化器索引中的八个 `repo.*` capability 条目指向的 Python 代码**确实已经存在**,但它们的 Phase 2 adapter 尚未落地,因此优化器路由器无法执行它们。索引条目是可发现的元数据,不是可调用的入口。

## 消息与投递(Message / Application / Cluster)

| 能力 | 状态 | 入口 |
|---|---|---|
| `generate`(消息) | 未开始 | 无 schema;策略见 [message-generation.md](message-generation.md) |
| `prepare` / `preview` | 已落地 | `jobagent applications preview` · `ApplicationPreviewService.prepare`(校验未通过的简历变体会被拒绝) |
| `approve` | 已落地 | `jobagent applications approve`(必须带 `--confirm`) · `ApplicationApprovalService.approve` |
| `send` | 已落地 | `jobagent applications send`(一次一份) · `DeliveryGate.send` |
| `audit` | 已落地 | `jobagent applications audit-log` · `ApplicationAuditor.record_attempt`;策略见 [audit-feedback.md](audit-feedback.md) |
| 平台投递连接器 | 已落地(仅猎聘) | `LiepinCliDeliverySource` 经 `liepin-cli job apply`;其余平台无连接器,`send` 一律拒绝并交人 |
| `resume_compatibility` | 仅契约 | `ResumeCompatibilityResult`、`CompatibilityThresholds` |

投递链路(prepare → preview → approve → send → audit)**已经可以执行**,猎聘的最后一跳也已接通。其余平台没有连接器,`send` 会以 `USER_INTERVENTION_REQUIRED` 停下,要求人在平台上自己完成提交,再用 `audit-log` 回看记录。

投递连接器与寻源连接器**分开注册**:一个平台可读,从不意味着可以向它提交。
这条链路上不可协商的几点:
- **一次只投一份。** 没有任何命令、函数或参数接受多份申请,`DeliveryGate` 里也没有循环。批量投递属于 `BatchApplication` 契约,仍是仅契约状态,不要为它写编排代码。
- **`job_kind` 只能来自搜索结果。** 上游要求它与搜索结果一致且「勿凭感觉填写」;取不到时投递直接拒绝,而不是在 1 与 2 之间猜——猜错会投到另一类职位上。
- **审批不可绕过。** `send` 在提交前的最后一刻重新校验四个摘要;任何一处变化都会抛 `STALE_APPROVAL` 并写入审计。
- **登录、CAPTCHA、验证、风控与限流不是重试理由。** 它们一律翻译为 `USER_INTERVENTION_REQUIRED`(限流按 `RISK_CONTROL` 上报),记入审计后交还控制权,按 [stop-conditions.md](stop-conditions.md) 停下。
- **审计写在失败路径上。** 成功、失败、中止与审批过期都会各写一条记录;从未发生的尝试不写记录。
