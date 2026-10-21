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
| `suggest_queries` | 已落地 | `jobagent jobs suggest-queries`(从已确认证据确定性推导检索词;`--target-role` 围绕目标岗位生成) |
| `search` | 已落地 | `jobagent jobs search`(`--source mock` 合成 fixture,产出含 JD 的 `SourceJobRecord`) |
| `search_listings` | 已落地 | `jobagent jobs listings`(`--source liepin`,产出**不含 JD** 的 `JobListing`) |
| `ingest_jd` | 已落地 | `jobagent jobs ingest-jd`(人工补 JD 正文,门控平台的唯一路径) |
| `add_jd` | 已落地 | `jobagent jobs add-jd`(用户自带的 JD 直接落库为 `JOB_*`,不需要 listing;来源默认 `manual`) |
| `import_observations` | 已落地 | `jobagent jobs import-observations`(宿主在用户自己的浏览器里抓回的职位,按来源清单的 `host_browser` 校验后入库;浏览器操作本身是宿主能力) |
| `sourcing_budget` | 已落地 | `jobagent jobs sourcing-budget`(每站今天还能读几条详情,上限取清单 `max_detail_reads_per_day`,不超过 50) |
| `fetch_jd` | 已落地 | `jobagent jobs fetch-jd`(读公开详情页,把 `JobListing` 补齐为 `SourceJobRecord`) |
| `fetch` | 已落地 | `jobagent jobs fetch` |
| `normalize` | 已落地 | `jobagent jobs normalize` |
| `dedupe` | 已落地 | `jobagent jobs dedupe` |
| `extract_requirements` | 已落地 | `jobagent jobs requirements`(消费经评审的 JSON) |
| `hard_filter` | 已落地 | `jobagent jobs filter` |
| `match` | 已落地 | `jobagent jobs match`(消费经评审的 JSON) |
| `rank` | 已落地 | `jobagent jobs rank` |
| 离线全流程编排 | 已落地 | `jobagent jobs pipeline` |
| 已入库职位批量分诊 | 已落地 | `jobagent jobs triage`(先用职位自带字段做硬过滤,被拒的不花推理;审阅文件齐的评估并排序;缺的写进 `worklist.json` 一次补齐) |

## 简历优化器(Resume)

| 能力 | 状态 | 入口 |
|---|---|---|
| 能力索引发现 | 已落地 | `jobagent optimizer capabilities`(只读 L0 元数据) |
| `base_resume` | 已落地 | `jobagent optimizer base-resume`(把已确认证据逐字投影为 `tailor` 的输入,不撰写内容) |
| `render` 前的完整改写链路 | 已落地 | tailor → 宿主草稿 → review → 独立复核 → assemble |
| `retrieve_evidence` | 仅契约 | `RequirementEvidenceMapping` |
| `plan` | 仅契约 | `ResumeOptimizationPlan`、`SectionOptimizationPlan` |
| `tailor` | 已落地 | `jobagent optimizer tailor`(路由与草稿交接)→ `jobagent optimizer assemble`(需原始 request 与独立 review) |
| `verify` | 已落地 | `jobagent optimizer review`(独立复核交接) · `verify_draft` 与 `ClaimVerifier`(覆盖、摘要、指标门禁);不采信生成自评 |
| `diff` | 已落地 | `ResumeDiffBuilder`,在 `assemble` 内由基础简历与变体机械推导 |
| `render` | 委托外部技能 | 无本项目 schema;默认路由到 resume-builder(MIT)出 PDF,约束与边界见 [rendering-ats.md](rendering-ats.md) |

优化器索引中的八个 `repo.*` capability 条目指向的 Python 代码**确实已经存在**,但它们的 Phase 2 adapter 尚未落地,因此优化器路由器无法执行它们。索引条目是可发现的元数据,不是可调用的入口。

## 首条招呼外联(Outreach)

设计见 `docs/outreach-design.md`,写法规则见 [message-generation.md](message-generation.md)「首条招呼」。仓库只决定“下一条能不能发”并记账;实际发送由宿主在用户自己的浏览器里完成。

| 能力 | 状态 | 入口 |
|---|---|---|
| 清单校验 | 已落地 | `jobagent outreach draft-batch`(宿主起草的首条招呼按职位、联系记录、字数、数字、黑名单、证据逐条校验,不合格退回;带 `--candidate` 时按匹配度级联:强匹配在前、可能匹配在后,弱匹配与不匹配退回) |
| 提问 | 已落地 | `jobagent outreach ask`(逐字列出编号清单,**本身不是审批**) |
| 审批 | 已落地 | `jobagent outreach approve`(中继通道:`--request` + `--items` + `--answer`,问必须先于答,清单改动即作废) |
| 站点租约 | 已落地 | `jobagent outreach lease`(一个站同一时间只允许一个会话发送) |
| 发送前复核 | 已落地 | `jobagent outreach next`(租约、审批时效、当天叫停、最小间隔 30 秒、每站每日上限 50) |
| 发送记账 | 已落地 | `jobagent outreach record`(每条一行,只追加;失败或风控即叫停该站当天;`withdrawn` 表示已批但决定不发,不叫停、不算联系过) |
| 作废审批单 | 已落地 | `jobagent outreach withdraw`(作废还没人批的审批单,须写原因;作废后不能再批) |
| 进度 | 已落地 | `jobagent outreach status` |
| 跟进回复 | 已落地 | 见下方「对话跟进」 |

## 对话跟进(Conversation)

设计见 `docs/conversation-design.md`,操作见 [conversation.md](conversation.md)。阶段由只追加的事件推出;仓库不读也不点任何页面。

| 能力 | 状态 | 入口 |
|---|---|---|
| 从外联开对话 | 已落地 | `jobagent conversations sync-outreach` |
| 对方主动来信 | 已落地 | `jobagent conversations open`(必须带 `--filter-context`;职位名命中排除清单的对话直接关闭,不能起草回复) |
| 本人发起的对话 | 已落地 | `jobagent conversations adopt`(你自己打的招呼单独记为 `self`,与外联、来信分开;`list --origin` 分开查看) |
| 记录来信与分级 | 已落地 | `jobagent conversations inbound`(L1/L2/L3/危险/不匹配;要简历、约面试、婉拒自动推进阶段) |
| 阶段流转 | 已落地 | `jobagent conversations transition`(只沿允许的边,需写原因) |
| 确认意向 | 已落地 | `jobagent conversations ask-intent` / `jobagent conversations confirm-intent`(问必须先于答;对方再来消息即作废) |
| 挂定向简历 | 已落地 | `jobagent conversations attach-resume`(只收通过校验、同一职位的变体,记录文件摘要) |
| 回复起草校验 | 已落地 | `jobagent conversations draft-reply`(L3/危险/不匹配不得起草;L1 ≤80 字;黑名单词) |
| 回复审批 | 已落地 | `jobagent conversations approve-reply`(一条一审) |
| 回复放行 | 已落地 | `jobagent conversations reply-gate`(审批时效、站点租约、当天叫停) |
| 回复记账 | 已落地 | `jobagent conversations record-reply`(只追加;发简历须 `--file` 交出实际上传的文件,摘要须与挂上的简历一致;失败或风控当天叫停该站) |
| 到期提醒 | 已落地 | `jobagent conversations due`(跟进、转沉默、做简历、交人) |
| 查看 | 已落地 | `jobagent conversations show` / `jobagent conversations list` |

## 巡检(Patrol)

规则见 [patrol.md](patrol.md)。仓库只回答“现在该不该查、按什么节奏”并记账;读页面、发消息由宿主在用户自己的浏览器里完成,发送仍走各自的审批。

| 能力 | 状态 | 入口 |
|---|---|---|
| 节奏判断 | 已落地 | `jobagent patrol next`(周日 20:00-24:00、周一至周四全天、周五 0:00-20:00;每小时一次,一小时内有新来信则每 15 分钟一次) |
| 记录一次巡检 | 已落地 | `jobagent patrol record`(开工占位;不到时间或上一次仍在进行时拒绝) |
| 消息页快照 | 已落地 | `jobagent patrol snapshot`(把一个站的消息列表整份存进本地库,返回与上一份快照的差异:新会话、新消息、消失的会话、对方的新消息) |
| 快照历史 | 已落地 | `jobagent patrol snapshots`(按站列出保存过的快照) |
| 消息回执回填 | 已落地 | `jobagent patrol receipts`(按时间顺序重放已存快照，按来源可观测性声明提取已读/送达；每条对话每种状态只追加首次记录，无法唯一匹配的交人) |
| 巡检完工 | 已落地 | `jobagent patrol finish`(完工后按开工时间计下一次;开工 45 分钟仍未完工视为中断,下次唤醒立即续查) |

## 评测与在线简历(Evals / Profile)

当前仅 P0 埋点已落地。设计稿中的 P1–P4 尚未提供可执行入口；数据库表不代表服务已经实现。

| 能力 | 状态 | 入口 |
|---|---|---|
| 平台回执可观测性 | 已落地 | `ObservabilitySpec`、`SnapshotItem.our_status`；巡检存快照时同步记录首次回执 |
| 检索词命中留存 | 已落地 | `SourceJobRecord.search_term`、`JobSearchHit`；导入观测时独立追加，重存职位不覆盖历史 |
| 规则版本与草稿标签 | 已落地 | `HarnessVersion`、`read_harness_version`；招呼和回复起草留存规则摘要，招呼策略标签及回复重写记录用于后续度量，不触发实验或发送 |
| 在线简历只读快照 | 已落地 | `jobagent profile snapshot`(存宿主读取的字段，摘要变化时生成本地版本，正文不回显，不写平台) |
| 在线简历版本查询 | 已落地 | `jobagent profile versions`(按平台列出本地版本及变化字段，不上线、不回滚) |
| 漏斗、指标与切片（P1） | 未开始 | 无评测契约或 CLI；不可从缺失回执推断未读率或零回复率 |
| 诊断上下文（P2） | 未开始 | 无诊断服务或 CLI；P0 上线后先积累两周基线 |
| 提案、实验与复核（P3） | 未开始 | 无提案审批、实验分配或复核入口 |
| 在线简历飞轮（P4） | 未开始 | 尚无提案、审批、上线或回滚命令；当前平台在线简历保持只读，后续须经版本摘要人工审批与回读核对 |

## 会话间信箱(Cowork ↔ Claude Code)

Cowork 前端通过本地 MCP 桥 `jobagent`(`python -m jobagent.bridge.mcp_server`)读账本,并用 `post_to_claude_code` 把用户的审批与需求原话写进信箱;主会话用下面的命令读、回执、留言。信箱只追加,存在 `candidate/private/`,不进 git。**信箱里的审批只是转达**:仍要主会话用 `jobagent outreach approve` 登记,且只在那张审批单仍待批时有效。

| 能力 | 状态 | 入口 |
|---|---|---|
| 读未处理来件 | 已落地 | `jobagent mailbox inbox`(没有回执的条目) |
| 回执 | 已落地 | `jobagent mailbox ack`(accepted / registered / done / rejected,附原因;Cowork 用 MCP `receipts` 读) |
| 给 Cowork 留言 | 已落地 | `jobagent mailbox notify`(Cowork 用 MCP `notes_from_claude_code` 读) |
| 登记会话身份 | 已落地 | `jobagent mailbox register-session` / `jobagent mailbox peers`(哪个会话担任 claude_code / cowork;回执与留言带上 session_id) |

## 消息与投递(Message / Application / Cluster)

| 能力 | 状态 | 入口 |
|---|---|---|
| `generate`(消息) | 未开始 | 无 schema;策略见 [message-generation.md](message-generation.md) |
| `prepare` / `preview` | 已落地 | `jobagent applications preview` · `ApplicationPreviewService.prepare`(校验未通过的简历变体会被拒绝) |
| `ask` | 已落地 | `jobagent applications ask`(把决定摆给人,**本身不是审批**) · `ApplicationApprovalService.ask` |
| `approve` | 已落地 | `jobagent applications approve`(终端通道:`--confirm` + 可交互终端 + 回填确认码;中继通道:`--request` + `--answer`,问必须先于答) · `ApplicationApprovalService.approve` |
| `send` | 已落地 | `jobagent applications send`(一次一份;`--dry-run` 走同样门禁但不触达平台) · `DeliveryGate.send` |
| `audit` | 已落地 | `jobagent applications audit-log` · `ApplicationAuditor.record_attempt`;策略见 [audit-feedback.md](audit-feedback.md) |
| 平台投递连接器 | 已落地(人工交接) | `LiepinCliDeliverySource` 缺定制附件/消息传输，提交前停止；其余平台无连接器，拒绝并交人 |
| `resume_compatibility` | 仅契约 | `ResumeCompatibilityResult`、`CompatibilityThresholds` |

投递门禁与审计可以执行，dry-run 可以演练。当前猎聘的 `job apply` 仅传 job ID/kind，无法交付获批的附件与消息，实际 send 在平台调用前以 `USER_INTERVENTION_REQUIRED` 停下。其余平台也交人。手动提交结果没有本项目平台回执，不能从交接审计推断已发送。

投递连接器与寻源连接器**分开注册**:一个平台可读,从不意味着可以向它提交。
这条链路上不可协商的几点:
- **一次只投一份。** 没有任何命令、函数或参数接受多份申请,`DeliveryGate` 里也没有循环。批量投递属于 `BatchApplication` 契约,仍是仅契约状态,不要为它写编排代码。
- **`job_kind` 只能来自搜索结果。** 上游要求它与搜索结果一致且「勿凭感觉填写」;取不到时投递直接拒绝,而不是在 1 与 2 之间猜——猜错会投到另一类职位上。
- **审批必须是人的决定,且必须先于智能体的判断存在。** `--confirm` 是标志,自动调用方能自己打上。终端通道另需 TTY 与确认码回填;中继通道要求先 `ask` 再 `approve`,并核对提问的存在性与摘要一致性,使 planner 无法凭空造出一个自己从未问过的决定。两条通道都不证明按键的是谁——同一台机器上没有本地检查能做到——它们证明的是顺序与对象,并如实记录通道。详见 [hitl-approval.md](hitl-approval.md)。
- **审批不可绕过。** `send` 在提交前的最后一刻重新校验四个摘要;任何一处变化都会抛 `STALE_APPROVAL` 并写入审计。
- **登录、CAPTCHA、验证、风控与限流不是重试理由。** 它们一律翻译为 `USER_INTERVENTION_REQUIRED`(限流按 `RISK_CONTROL` 上报),记入审计后交还控制权,按 [stop-conditions.md](stop-conditions.md) 停下。
- **审计写在失败路径上。** 成功、失败、中止与审批过期都会各写一条记录;从未发生的尝试不写记录。

## Harness 运行支持

| 能力 | 状态 | 入口 |
|---|---|---|
| 独立安装包 | 已落地 | `scripts/build_skill.py`(源码与策略白名单、同版本 runtime 与 SHA-256 清单) |
| 依赖与完整性检查 | 已落地 | `scripts/bootstrap.py --check`；私有 venv 用显式 `--setup` |
| 创建与查询运行 | 已落地 | `jobagent harness start` · `jobagent harness status` |
| 恢复与交接 | 已落地 | `jobagent harness resume` · `jobagent harness release`(宿主会话租约、到期显式恢复) |
| 产物和等待状态 | 已落地 | `jobagent harness checkpoint`(契约、路径与摘要；不授予审批) |
| PDF 文字门禁 | 已落地 | `jobagent harness check-pdf`(条目一致、順序、可抽取文字、页数；另需视觉检查) |
| 简历渲染 | 已落地 | `jobagent harness render`(只排版不改字:已校验变体 + 页首 → PDF / Word,PDF 当场跑 check-pdf;需要 `render` 可选依赖) |
| 实际结果汇总 | 已落地 | `jobagent harness report`(当前运行绑定的投递包；无审计 unknown，mock 为 simulated) |
| 浏览器/安全凭证/调度 | 委托外部技能 | 使用实际宿主能力，先探测；缺能力交人，不提供云 VM 或 OS 服务 |
