# 能力目录

每一项能力都具备类型化的输入与输出契约、显式错误、无隐藏副作用、独立测试,以及一个可直接从 Python 调用的边界。

状态含义:

- **已落地** —— 有 Python 服务与 CLI 命令,现在就能调用。
- **仅契约** —— 只有 Pydantic schema,没有服务、没有 CLI。**不要假装它可调用**;需要它时,产出经人工评审的类型化 JSON,并说明这一步尚未自动化。
- **未开始** —— 连 schema 都还没有。
- **委托外部技能** —— 本项目不实现,由一个外部 Agent Skill 承担;该技能是下游消费者,消费本项目已校验的产物,**不替代任何契约或门禁**。上游边界见 [oss/source-manifest.yaml](oss/source-manifest.yaml)。

## 候选人(Candidate)

Personal AI 默认入口见 [宿主接入](../../../hosts/personal-ai/README.md)。GitHub 读取、私有持久记忆、网页、定时和通知委托实际宿主，需逐项验收；公开代码可用不代表 Muse 真实账号已接通。旧本地桥接不是新入口的前置条件。

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
| 双层搜索学习 | 已落地 | `jobagent jobs learn-search`：原始 signal（岗位偏好与文案反馈分开）→ 引文核验、独立正例与反例 → 有版本的软优先级；用户主动加岗可作为正例，最多增加两个查询，不改硬条件、事实或审批；私有存储与调度委托宿主 |
| `search` | 已落地 | `jobagent jobs search`(`--source mock` 合成 fixture,产出含 JD 的 `SourceJobRecord`) |
| `search_listings` | 已落地 | `jobagent jobs listings`(`--source liepin`,产出**不含 JD** 的 `JobListing`) |
| `ingest_jd` | 已落地 | `jobagent jobs ingest-jd`(人工补 JD 正文,门控平台的唯一路径) |
| `add_jd` | 已落地 | `jobagent jobs add-jd`(用户自带的 JD 直接落库为 `JOB_*`,不需要 listing;来源默认 `manual`) |
| `import_observations` | 已落地 | `jobagent jobs import-observations`(宿主在用户自己的浏览器里抓回的职位,按来源清单的 `host_browser` 校验后入库;浏览器操作本身是宿主能力) |
| 读取尝试门禁 | 已落地 | `jobagent jobs reserve-read` · `jobagent jobs record-read`：原子预留和回执；动态初始化流程绑定所属 run_id，共用轮次与日消耗；重放 allowed=false，受限停站；浏览器由宿主执行 |
| 观察历史 | 已落地 | `jobagent jobs observation-history`：只回显追加观察的版本、摘要与类型；完整面板可按真实平台 ID 与面板身份采集，历史未验证记录不追认全文 |
| 整轮处理对账 | 已落地 | `jobagent jobs check-coverage`：每条输入恰有一个去向；完整采集须有可访问/已加载声明，部分采集保留检查点；不负责翻页或调度 |
| `sourcing_budget` | 已落地 | `jobagent jobs sourcing-budget`（查询尝试、列表观察、详情尝试与旧观测估算分别报告；来源默认每日50详情，显式muse-expanded-v1政策允许每日240；两种读取入口共用已消耗额度与停站记录，动态额度仍受来源清单约束） |
| 寻源轮次 | 已落地 | `jobagent jobs sourcing-start`（动态流程以 --rules-file 固定已确认查询、每查询取数、轮次详情与日额度；参数或来源政策冲突拒绝，不自动扩档） |
| 读取预占 | 已落地 | `jobagent jobs sourcing-reserve`（原子预占；仅新 allowed=true 可执行；失败/重复读取不退额） |
| 读取结果 | 已落地 | `jobagent jobs sourcing-result`（追加结果；gate 停该站当天预占；不授予发送权） |
| 每查询取数与精确去重 | 已落地 | `jobagent jobs sourcing-take`（绑定真实查询尝试与冻结 TOP_PER_QUERY，回显期望/实际/不足/重复，只按同来源平台 ID 跨查询去重；不证明已遍历全部页面） |
| `search_log` | 已落地 | `jobagent jobs search-log`(每次搜索都记一笔:站、检索词、列出几条、其中新职位几条;零结果也记) |
| `search_plan` | 已落地 | `jobagent jobs search-plan`(按站给出这一轮该用的检索词:多数名额轮换最久没搜过的词,一个名额给历史上带出强匹配/可能匹配最多的词;附每个词的搜索次数、新增、命中与匹配产出) |
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

| JD原文快照 | 已落地 | `jobagent jobs snapshot`（私有原文版本与独立发现） |
| 快照历史 | 已落地 | `jobagent jobs snapshots`（按岗位读取原文历史和多查询归因） |

| JD因子化 | 已落地 | `jobagent jobs factorize`（私有输入、类型校验、无模型/浏览器调用） |
| 词库绝对重算 | 已落地 | `jobagent jobs lexicon-update`（私有输入、类型校验、无模型/浏览器调用） |
| 历史词库读取与回滚 | 已落地 | `jobagent jobs lexicon-show`（私有输入、类型校验、无模型/浏览器调用） |
| 组合查询计划 | 已落地 | `jobagent jobs combinations`（私有输入、类型校验、无模型/浏览器调用） |
| 查询计划反查 | 已落地 | `jobagent jobs combinations-report`（私有输入、类型校验、无模型/浏览器调用） |

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
| 固定 Word 母版正文修改 | 已落地（Python 适配器） | `TemplatePatch` / `patch_template`：源摘要、原文、允许段落及文字预算校验；保留其他包成员。混合非粗体样式采用明确逐run修改；事实复核和同环境分页/位置核对仍单独必需。技能入口 `skills/jd-grounded-template-tailoring/SKILL.md` |

优化器索引中的八个 `repo.*` capability 条目指向的 Python 代码**确实已经存在**,但它们的 Phase 2 adapter 尚未落地,因此优化器路由器无法执行它们。索引条目是可发现的元数据,不是可调用的入口。

## 首条招呼外联(Outreach)

设计见 `docs/outreach-design.md`,写法规则见 [message-generation.md](message-generation.md)「首条招呼」。仓库只决定“下一条能不能发”并记账;实际发送由宿主在用户自己的浏览器里完成。

| 能力 | 状态 | 入口 |
|---|---|---|
| 清单校验 | 已落地 | `jobagent outreach draft-batch`(宿主全文生成并独立复核；按职位、联系记录、数字、禁用词、证据逐条校验，不设置首招字数硬上限；带 `--candidate` 时按匹配度级联，弱匹配与不匹配退回) |
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

当前仅 P0 的部分埋点已落地，操作与停止条件见 [evals.md](evals.md)。设计稿中的 P1–P4 尚未提供可执行入口；数据库表不代表服务已经实现。

| 能力 | 状态 | 入口 |
|---|---|---|
| 平台回执可观测性 | 已落地 | `ObservabilitySpec`、`SnapshotItem.our_status`；巡检存快照时同步记录首次回执 |
| 检索词命中留存 | 已落地 | `SourceJobRecord.search_term`、`JobSearchHit`；导入观测时独立追加，重存职位不覆盖历史 |
| 规则版本与草稿标签 | 已落地 | `HarnessVersion`、`read_harness_version`；招呼和回复起草留存规则摘要，招呼策略标签及回复重写记录用于后续度量，不触发实验或发送 |
| 在线简历只读快照 | 已落地 | `jobagent profile snapshot`(存宿主读取的字段，摘要变化时生成本地版本，正文不回显，不写平台) |
| 在线简历版本查询 | 已落地 | `jobagent profile versions`(按平台列出本地版本及变化字段，不上线、不回滚) |
| 在线简历修改提案 | 已落地 | `jobagent profile propose`(针对当前版本写改动；只能改已有段落，字数按来源清单上限，引用证据须已确认，拒绝自证句；判定规则写进提案摘要) |
| 在线简历修改提问 | 已落地 | `jobagent profile ask`(逐段列出现在与改后原文、依据和判定规则；只提问，不算批准) |
| 在线简历修改批准 | 已落地 | `jobagent profile approve`(须先有提问；人的原话逐字存档；提问后任一站版本变化即作废) |
| 在线简历修改放行 | 已落地 | `jobagent profile gate`(核对批准、当前版本与是否已记账，给出要填写的原文；仓库不操作网页) |
| 在线简历修改记账 | 已落地 | `jobagent profile record`(applied 必须附回读，回读摘要与批准一致才生成 agent 版本，否则记 mismatch；intervention / failed 交人) |
| 漏斗、指标与切片（P1） | 未开始 | 无评测契约或 CLI；不可从缺失回执推断未读率或零回复率 |
| 诊断上下文（P2） | 未开始 | 无诊断服务或 CLI；P0 上线后先积累两周基线 |
| 提案、实验与复核（P3） | 未开始 | 无提案审批、实验分配或复核入口 |
| 在线简历飞轮（P4）其余部分 | 未开始 | 条件回滚、收口与由诊断触发的提案尚无入口；回滚目前要作为一份新提案重新提问和批准 |

## 会话间信箱(Cowork ↔ Claude Code)

Cowork 前端通过本地 MCP 桥 `jobagent`(`python -m jobagent.bridge.mcp_server`)读账本,并用 `post_to_claude_code` 把用户的审批与需求原话写进信箱;主会话用下面的命令读、回执、留言。信箱只追加,存在 `candidate/private/`,不进 git。**信箱里的审批只是转达**:仍要主会话用 `jobagent outreach approve` 登记,且只在那张审批单仍待批时有效。

| 能力 | 状态 | 入口 |
|---|---|---|
| 读未处理来件 | 已落地 | `jobagent mailbox inbox`(没有回执的条目) |
| 回执 | 已落地 | `jobagent mailbox ack`(accepted / registered / done / rejected,附原因;Cowork 用 MCP `receipts` 读) |
| 给 Cowork 留言 | 已落地 | `jobagent mailbox notify`(Cowork 用 MCP `notes_from_claude_code` 读) |
| 登记会话身份 | 已落地 | `jobagent mailbox register-session` / `jobagent mailbox peers`(哪个会话担任 claude_code / cowork;回执与留言带上 session_id) |

## 手机推送(飞书 bot)

账本有新东西时,经飞书 bot(`lark-cli im +messages-send --as bot`)给本人推一条消息。会触发推送的有：待审批问题(含招呼原文)、招聘方新来信、新入库的强匹配和可能匹配职位、当天被叫停的站。巡检完成只会捎带进消息，单独不会触发推送。每一项按键去重，发送成功才记入 `.jobagent/feishu_push_state.json`，失败的下次重试，重跑不会重复发。接收人写在 `.jobagent/feishu_push.json`，三选一：`chat_id`、`user_id`(应用 bot，经 lark-cli 发)，或 `webhook` 加可选 `secret`(群自定义机器人，不需要建应用，也不需要企业认证)。没有这个文件就不推送。**推送本身只是告知**；审批可回到对话里回复，也可在飞书审批卡片上提交(见下表)。

| 能力 | 状态 | 入口 |
|---|---|---|
| 推送更新 | 已落地 | `jobagent notify feishu`(`--dry-run` 只打印不发、不记)。`patrol finish`(可带 `--report <文件>`，把巡检汇报原文一并推送，超过 6000 字截断)与 `outreach ask` 结束后在配置存在时自动推送，结果写到 stderr，失败不影响原命令 |
| 飞书卡片审批 | 已落地 | 应用 bot 配置下，`outreach ask` 后自动给每个待批问题发一张审批卡片(勾选 + 可改原文 + 提交)，`jobagent notify feishu` 也会补发。`jobagent notify feishu-listen`(`--hours 8`)在本机监听提交：只认 `user_id`/`owner` 本人、只认本机发出且未处理的卡片、每张卡只登记一次；勾选即批准、没有第二轮：未改的条目以提交内容为原话登记；改过的条目按本人改写生成新批次，并以卡片里的原文为原话当场登记(仍须过首条招呼规则，不过则卡片写明原因、可改后重交)。卡片不触发发送，发送仍由浏览器会话按租约和节奏执行 |

## 消息与投递(Message / Application / Cluster)

原生逐岗位首条招呼卡片已支持上一条/下一条、编辑草稿留存、单项批准与显式回绝，宿主入口为 `feishu_approval.send_question_card`；旧卡兼容。回绝反馈可由 `bridge.sourcing_feedback.next_fetch_strategy` 在下一次显式采集前消费，生成有版本的优先级计划；不启动轮询、不改变硬筛选或发送许可。`demo_mode=True` 仅用于合成 UI 验证，不产生真实审批或偏好。详见 `docs/feishu-paged-approval-2026-10-26.md`。此能力不包含定向简历的原生卡片审批桥或通用自进化编排。

| 能力 | 状态 | 入口 |
|---|---|---|
| 首条招呼全文 AI 生成 | 已落地（通用稿与两类历史完整 JD 的真实模型验收通过） | `jobagent greetings generate`：默认稿、完整 JD 定向稿及反馈重写；`GreetingRequest` → `GreetingDraft` → 独立 `GreetingReview` → `GreetingReport`，使用 [greeting-ai.md](greeting-ai.md)，不读取句库、不授予审批；通过的定向稿保留来源绑定，再进入既有首招门禁 |
| 其他消息自动生成编排 | 未开始 | 求职信与后续回复的统一自动生成仍无独立入口；策略见 [message-generation.md](message-generation.md) |
| `prepare` / `preview` | 已落地 | `jobagent applications preview` · `ApplicationPreviewService.prepare`：非 mock CLI 须提供 `--artifact` 最终 PDF/Word，可选 `--header`；结构检查、文件字节与摘要绑定，不授予发送权 |
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

## 动态变量与版本治理

| 能力 | 状态 | 入口 |
|---|---|---|
| 变量定义与消费状态 | 已落地 | `jobagent rules definitions`：类型、用户参数/平台参考/不变量及实际消费者；不带个人默认值 |
| 首次表单与普通运行准备 | 已落地 | `jobagent rules prepare`：首次或本人主动修改才返回配置问题；普通运行跨轮次/任务类型/会话只读复用，缺值与冲突只报阻塞，不重开交互、不占额度 |
| 登记首次初始化 | 已落地 | `jobagent rules initialize`：核对当前版本及必需确认值后保存初始化身份，不再请求相同参数确认；已有确认档升级保留身份 |
| 单变量修改提问 | 已落地 | `jobagent rules propose`：绑定候选人、来源、旧版本与一项新值；初始化后还需匹配的本人主动调整记录；只保存提问，不生效 |
| 参数确认与激活 | 已落地 | `jobagent rules approve`：原提问摘要与本人明确答复；旧版本冲突拒绝，事务内只更新指定变量；不授予外部动作权限 |
| 生效值与待公告变更 | 已落地 | `jobagent rules effective`：读取/导出私有快照与待公告变更；读取不算通知完成 |
| 参数历史 | 已落地 | `jobagent rules history`：追加版本及来源；不追溯重算旧终态 |
| 公告回执 | 已落地 | `jobagent rules acknowledge`：宿主提供实际通知参考后记账；不发送消息 |
| 动态条件判断 | 已落地 | `jobagent rules evaluate`：默认核对权威私有库当前 head；显式 --historical 标明历史/未核验当前；纯计算，不持久化队列、不调度、不自动优化 |
| 既有入口绑定 | 已落地 | `jobs` 的薪资筛选、查询计划、详情预算及 `greetings generate` 支持显式 `--rules-file`；校验摘要与候选人，冲突报错，不静默回落 |
| pipeline 策略兼容守卫 | 已落地 | 生产状态/历史及比例派生写入在事务内核对当前候选人策略；适用缺值或不兼容返回 not_integrated，相关业务记录不变；事实指标计数独立 |
| 宿主专属变量执行 | 委托外部技能 | 面板同步、首次采集数量和 BOSS 发送随机节律等仍由 host 执行；MCP 已接入下表所列网关，交接和记录均不授予投递权 |

详细协议见 [dynamic-variables.md](dynamic-variables.md)。平台额度和凭证期限只作带日期的参考，不能由用户调参改写；队列快照与单岗 HOLD 不进入参数表。

## MCP 实际调用与交接

只支持经网关的搜索/查看，绑定现有配置化寻源轮次、候选人、规则与代码版本。实际派发才计量，准备和连接初始化不扣额；宿主绕过网关直接调用的外部工具不受本地库拦截。详见 [mcp-runtime.md](mcp-runtime.md)。

| 能力 | 状态 | 入口 |
|---|---|---|
| 有版本 MCP 轮次 | 已落地 | `jobagent mcp round-start`：冻结确认参数与所属寻源轮次，不发起业务调用、不预扣投递数 |
| 实际调用预算与状态 | 已落地 | `jobagent mcp status`：读取真实计数、前轮扣额、版本及停站状态 |
| 只读 MCP 批次 | 已落地 | `jobagent mcp batch`：私有 stdio 传输、只读工具核验、批内限并发/批间串行；搜索/查看共计，TOP/详情/日额共用，429001 持久停站 |
| 未知调用结果核验 | 已落地 | `jobagent mcp reconcile`：追加 host_observed 来源及正向回读，保留原未知与消耗，不重试、不自动解除日停站 |
| 关闭实际轮次 | 已落地 | `jobagent mcp round-close`：结果已解决才关闭，冻结前轮真实投递观察供后轮扣额 |
| 单项投递交接检查 | 已落地 | `jobagent mcp delivery-prepare`：一项在途、间隔与前项回读检查；executable=false，不批准、不发送 |
| 宿主投递结果观察 | 已落地 | `jobagent mcp delivery-record`：保存真实来源、外部身份与正向回读；executed_by_gateway=false，不执行 apply |
| 未知投递结果核验 | 已落地 | `jobagent mcp delivery-reconcile`：追加真实核验，保留原未知观察与停止记录，不重发 |

猎聘获批定制附件与消息传输仍不受支持；交接检查不能替代原逐项批准或连接器能力。未确认批大小只阻塞，不激活建议值，也不重开普通任务的配置对话。

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

## 本地执行 Worker

接口与运行示例见 [worker.md](worker.md)。这里只接收结构化观察、释放一条获批招呼及校验回读，不内置浏览器控制、批准入口或发送循环；读取能力不授予平台写入权限。

| 能力 | 状态 | 入口 |
|---|---|---|
| 观察入库与完成回执 | 已落地 | `jobagent worker ingest`（复用来源校验；职位、请求回执与完成事件在同一事务提交，同号同输入幂等） |
| 单项获批任务领取 | 已落地 | `jobagent worker claim-greeting`（复核审批原问题、当前正文与职位、站点租约及节奏；并发领取去重） |
| 发送前一次性授权 | 已落地 | `jobagent worker authorize-greeting`（重新核对门禁；授权消费后不能再次领取发送权限，异常须核验） |
| 回读记账 | 已落地 | `jobagent worker record-greeting`（准确正文和 URL 才可登记 sent；不明确或门禁改变登记 intervention，审计与完成事件同事务） |
| 任务状态 | 已落地 | `jobagent worker show`（读取持久化回执；父代理的 SUCCESS 不能替代任务完成证据） |
| 完成事件与确认 | 已落地 | `jobagent worker events` · `jobagent worker ack`（按次读取和幂等确认，不启动轮询或监听） |
| Antigravity 浏览器与模型运行 | 委托外部技能 | 调用受允许的宿主工具；本地页面已验证，真实平台执行、事件唤醒与评测进化闭环不因此视为落地 |

## Codex 文本协调器

| 能力 | 状态 | 入口 |
|---|---|---|
| 本机文本模型执行器 | 已落地 | 内部 `CodexTextRunner.run`，固定 `gpt-6.1-sol`，结构化文字输入和契约输出；只读临时目录，不加载用户 MCP 配置，逐次关闭图像、浏览器、shell、应用和插件；超时/配置错误/工具活动拒绝结果，不自动重试。已用本机现有登录完成一次合成文本调用；不授予审批或发送权限 |
| 本机职位推理适配 | 已落地（内部接口，真实质量联调未通过） | `CodexJobReasoningProvider.generate` 连接现有需求提取和证据映射契约，使用同一文字执行器；需求提取只向模型传职位编号和 JD 正文。现有源文、证据与确定性计分继续生效。单元测试通过；历史 JD 实际调用的汇总字段、元数据引文曾被门禁拒绝，尚无真实匹配通过证据，不能据此计入三站本轮结果 |
| 事件 webhook 与模型任务持久化 | 未开始 | 当前 `worker_events` 可按次读取和确认，尚无自动转发、webhook 接收器或持久化模型任务 |
| 搜索计划与 Gemini 轮询队列 | 未开始 | 浏览器、截图与采集均归 Gemini；当前 Worker 入口不包含自动搜索调度 |
| 选择/改写反馈与策略版本闭环 | 未开始 | 需要连接本人选择、最终批准原文、实际执行结果及后续策略版本；不得修改已批准内容或候选人事实 |

## JD 与已发送观察补充

| 能力 | 状态 | 入口 |
|---|---|---|
| 审计回读绑定建档 | 已落地 | `jobagent tracking start`；仅消费已有批准与 sent 审计，不发送 |
| 预执行门禁投影 | 已落地 | `jobagent tracking pending`；读取各站现有租约，不授予执行权 |
| 追加观察与状态转移 | 已落地 | `jobagent tracking event`；CAS版本、证据校验、暂停/归档 |
| 当前状态 | 已落地 | `jobagent tracking status`；候选人作用域 |
| 到期只读检查清单 | 已落地 | `jobagent tracking due`；未切换候选人兼容统一48小时；切换pipeline后due为空、旧档案只读 |
| 追加历史 | 已落地 | `jobagent tracking history`；关闭后保留 |
| 结果模式报告 | 已落地 | `jobagent tracking report`；不自动调整词库 |


## 人工加岗闭环

| 能力 | 状态 | 入口 |
|---|---|---|
| 人工入口持久入队与幂等 | 已落地 | `jobagent intake enqueue` |
| 不可变列表编号或卡片身份映射 | 已落地 | `jobagent intake selection` |
| 实际listing或缓存岗位身份绑定 | 已落地 | `jobagent intake resolve` |
| 完整原文与预算行动绑定 | 已落地 | `jobagent intake snapshot` |
| 特征与明确兴趣自动接线 | 已落地 | `jobagent intake factorize` |
| 宿主草稿与原文/硬条件校验 | 已落地 | `jobagent intake draft` |
| 独立复核产物与摘要绑定 | 已落地 | `jobagent intake review` |
| 现有外联批次绑定，不授予批准 | 已落地 | `jobagent intake batch` |
| 本人兴趣追加或撤回 | 已落地 | `jobagent intake interest` |
| 暂停、明确恢复与关闭 | 已落地 | `jobagent intake control` |
| 恢复动作契约与按需私有上下文 | 已落地 | `jobagent intake next` |
| 当前双分支状态 | 已落地 | `jobagent intake status` |
| 完整追加历史的脱敏视图 | 已落地 | `jobagent intake history` |
| 候选人/域作用域队列恢复 | 已落地 | `jobagent intake list` |
| 汇总全域样本并事务激活词库/计划 | 已落地 | `jobagent intake strategy` |
| 读取活跃MD/计划并检查新鲜度 | 已落地 | `jobagent intake active` |
| 下一实际寻源轮次领取固定计划 | 已落地 | `jobagent intake claim` |
| 真实预算查询结果与计划归因 | 已落地 | `jobagent intake record-search` |


## 宿主迁移与验收

| 能力 | 状态 | 入口 |
|---|---|---|
| 只读检查JSONL字段结构，不显示源值 | 已落地 | `jobagent host inspect-queue` |
| 备份和临时副本迁移，精确校验行与身份；可关联原始已发声明文件 | 已落地 | `jobagent host migrate-queue` |
| 校验行哈希、行ID与队列绑定 | 已落地 | `jobagent host verify-migration` |
| 从数据库生成JSONL视图，不改变状态权威 | 已落地 | `jobagent host project-queue` |
| 仅迁移后无新活动且备份匹配时回滚 | 已落地 | `jobagent host rollback-migration` |
| 原始发送引用与已有正式跟踪证明一致后绑定 | 已落地 | `jobagent host bind-tracking` |
| 记录消息/搜索各自三态，登录失效暂停对应消息跟踪并要求通知 | 已落地 | `jobagent host page-observe` |
| 按来源和页面读取沉降状态 | 已落地 | `jobagent host page-status` |
| 从真实账本与有出处宿主计数生成不可变轮次报告 | 已落地 | `jobagent host round-report` |
| 读取候选人作用域报告 | 已落地 | `jobagent host round-show` |
| 校验两轮核心证据，保留真实宿主待验收状态 | 已落地 | `jobagent host verify-rounds` |
| 输出未知值为空的私有报告模板 | 已落地 | `jobagent host round-template` |

| 旧队列全文回填清单 | 已落地 | `jobagent host backfill-plan` | 原ID与私有优先级，partial不入策略 |
| 旧摘要到全文谱系 | 已落地 | `jobagent host backfill-attach` | 原门禁校验真实读取后追加，不覆盖旧摘要 |

| 初稿与最终稿差异 | 已落地 | `jobagent host message-diff` | 全文哈希与变化位置，语义类别为宿主提案 |
| 差异成熟度 | 已落地 | `jobagent host diff-report` | 三个不同岗位才进入评估，无自动权重 |
| 具体文案规则提案 | 已落地 | `jobagent host rule-propose` | 绑定当前评估摘要，待本人确认 |
| 逐条规则确认 | 已落地 | `jobagent host rule-confirm` | 准确规则摘要与本人原话；独立于文案Accept |
| 读取本人已确认规则 | 已落地 | `jobagent host confirmed-rules` | 私有候选人隔离，默认空列表 |


## 后段流程与累计飞轮

| 能力 | 状态 | 入口 | 边界 |
|---|---|---|---|
| 九态流程入库 | 已落地 | `jobagent pipeline create` | 实际岗位或已解析intake，候选人隔离 |
| 有据流程转移 | 已落地 | `jobagent pipeline transition` | 固定转移图与证据，非法输入写拒绝审计 |
| 流程观察与到期废止 | 已落地 | `jobagent pipeline observe` | 真实观察；动态策略须兼容生产语义，缺值/冲突拒绝相关写入，不从徽标推断 |
| 历史发送补证绑定 | 已落地 | `jobagent pipeline bind-send` | 原审批及准确回读，不构造时间 |
| 新联系轮次绑定原获批回复 | 已落地 | `jobagent pipeline bind-reply` | 仅后续轮次，读取既有ask与approval，不审批、不发送 |
| 同步真实完整JD与草稿 | 已落地 | `jobagent pipeline sync` | 只消费绑定intake产物，变化保留历史 |
| 流程当前记录 | 已落地 | `jobagent pipeline list` | 候选人显式指定，返回job与meta |
| 统一岗位表单 | 已落地 | `jobagent pipeline form` | 标准pipeline_job_form视图 |
| 流程转移历史 | 已落地 | `jobagent pipeline history` | 只追加历史，required candidate |
| 流程到期只读清单 | 已落地 | `jobagent pipeline due` | 核对当前动态策略兼容性，不把不兼容的固定截止点当当前结果；不发送、不自动浏览 |
| 私有迁移字段检查 | 已落地 | `jobagent pipeline inspect` | 只输出形状与摘要，不输出原文 |
| 离线流程迁移 | 已落地 | `jobagent pipeline migrate` | 显式私有映射、备份、临时验证、原子激活 |
| 流程迁移校验 | 已落地 | `jobagent pipeline verify-migration` | required candidate与原ID/来源一致性 |
| 流程队列投影 | 已落地 | `jobagent pipeline project` | required candidate，不覆盖原始输入和备份 |
| 受保护流程回滚 | 已落地 | `jobagent pipeline rollback` | required candidate，后续事实存在则拒绝 |
| 累计漏斗指标 | 已落地 | `jobagent pipeline metrics` | 真实历史与来源切片，窗口比率仅参考 |
| 累计比率诊断 | 已落地 | `jobagent pipeline diagnose` | 持久指标引用，确认因子须与生产消费者兼容，无绝对样本门槛 |
| 指标及来源证据 | 已落地 | `jobagent pipeline metric-show` | required candidate，透明核对分子分母 |
| 归因诊断详情 | 已落地 | `jobagent pipeline diagnosis-show` | required candidate，附排除和累计比率 |
| 流程优化规则提案 | 已落地 | `jobagent pipeline rule-propose` | 当前诊断与准确规则，默认不生效 |
| 本人逐条规则确认 | 已落地 | `jobagent pipeline rule-confirm` | 准确规则摘要与本人原话，候选人隔离 |
| 已确认流程规则 | 已落地 | `jobagent pipeline confirmed-rules` | 只读取当前候选人有效规则 |
| 优化效果复核 | 已落地 | `jobagent pipeline rule-review` | 优化后累计比率与基线比较，回滚仍提案 |
| 流程规则提案详情 | 已落地 | `jobagent pipeline rule-show` | required candidate，具体规则可审阅 |
