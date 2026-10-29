# 岗位后段 Pipeline 与飞轮接线

本文记录公开核心的接口、证据边界和宿主验收方法。个人履历、岗位原文、消息、实际批次大小、原始编号、求职条件、来源时间和映射配置只留在宿主私有区。公开示例均为结构示例，不代表任何用户的真实记录。

代码升级不会切换运行中的 Muse 任务。本次没有执行真实私有迁移、访问招聘网站、发消息、发送附件、创建任务或送达通知；真实验收保持 unverified，报告中的 real_browser_verified=false。

## 数据与职责

- intake 保存聊天 URL、不可变列表编号和卡片请求，处理身份、完整 JD、独立草稿复核、兴趣信号和下一轮查询计划；缺身份的人工条目先留在这里。
- pipeline_jobs 是已确认平台岗位的后段当前态权威；pipeline_job_form 是统一表单视图，包含职位、薪资、JD、拟发送/实际发送招呼、简历与状态。不要另写各自口径的查询来拼表。
- pipeline_state_history、pipeline_requests、pipeline_observations 追加保存转移、原请求回放和证据；pipeline_meta 保存联系轮次、版本、来源绑定、证明状态和观察时间，不复制另一套当前态。
- pipeline_stage_metrics、pipeline_diagnoses 和相应 context/report 表保存不可变累计计算与诊断。已确认规则复用私有 message_rule_* 账本，优化复核追加 pipeline_rule_reviews。
- 原始文件保留；JSONL/Markdown 是投影。代码、私有数据库和引用文件必须固定同一版本；每个候选人使用自己的持久库，所有命令显式传 --database。

主表使用约定英文字段，不增加 status/stage/phase 同义列。jd_text/jd_text_hash 与 jd_points 分开；draft_* 与 sent_* 分开；定制简历的版本、文件 ID、请求证据和发送时间各自保留。实际未发送或证明未齐时，不能拿拟稿填 sent_*。未知值保留 NULL，展示层可说明缺项。

## 九态与唯一时钟

正常漏斗为 draft_pending → greeting_sent → greeting_read → initial_contact → resume_requested → resume_sent → interview_pending → interviewed。对方直接邀约可从 initial_contact 到 interview_pending。其余跳跃由模型和事务服务拒绝并记隐私化拒绝日志。

未读发送态也允许 greeting_sent → abandoned。greeting_read、initial_contact、resume_requested、resume_sent、interview_pending 可按真实证据进入 abandoned；interviewed 只接受本人主动放弃或已验证岗位关闭，不能以无回复自动关闭。draft_pending 不凭空走到发送或面试后段。abandoned 为终态，旧行不复活。

已验证发送且尚待跟进的唯一静默截止点为：

~~~text
max(sent_at, 已确认read_at, 最后实质回复时间, 已验证resume_sent_at) + 48小时
~~~

时间必须来自真实发送审计、已读/对话证据或已确认附件结果；实际没有的时间不补造。pipeline due 返回本轮需核对的行、当前版本、deadline_at 与 expiry_due；这份清单不执行网页，也不直接把岗位废止。宿主先实际读取已加载对话，再提交 no_reply 观察；达到截止点才按 read_no_reply_2d 或 no_reply_2d 废止。观察次数仅保留审计意义，不授予额外宽限。

实质回复用既有 conversations inbound 的真实来源时间重置时钟，不能用“本次打开页面的时间”重置旧消息。角标/未读数只记疑似；系统通知不算实质建联。明确拒绝、已验证岗位关闭和本人主动放弃分别用 employer_rejected、job_closed、user_abandoned。岗位关闭须目标匹配的详情/列表证据，搜不到不足以确认关闭。

proof_pending、无精确发送时间、暂停和终态都不能凭空产生到期废止。登录或回读异常先暂停；恢复需要本人原话。恢复后先核对真实对话，再按实际活动时间判断，不把无法加载的页面当无回复。匹配原目标的回读不一致会被门禁拒绝并暂停，宿主负责实际通知本人，不重发、不换账号或绕验证。

同岗重新联系必须有新的本人请求、独立联系轮次、独立 pipeline_id 与新批准/发送证明。活动行唯一索引保留一个当前联系轮次，旧 abandoned 行与审计继续保留；不能借搜索结果复活旧行或重复使用旧 send_reference。

## 命令与最小返回

以下路径和标识符由宿主替换为真实私有值；命令参数以同版本 --help 和 schemas 契约为准。

| 接口 | 输入 / 返回 | 失败时 |
|---|---|---|
| pipeline create | PipelineCreate：event_id、candidate_id、真实 normalized_job_id 或 intake_id、evidence_reference、私有 salary_minimum_k/currency；返回 job + meta | 身份未解析、错候选人、重复活动行或未迁移旧权威时停止 |
| pipeline transition | PipelineTransition：当前 from/to、expected_version、带时区 changed_at、证据种类/引用、必要的现有审计或会话 ID；返回 job + meta | 非法跳跃、证据错配、过期版本、未批准/回读不一致均拒绝 |
| pipeline observe | PipelineObservation：no_reply/substantive_reply/suspected_reply/pause/resume 与真实来源证据；返回 job + meta | 未加载不能写 no_reply；resume 缺本人原话停止 |
| pipeline bind-send | PipelineBindSend：原 pipeline、当前版本、真实 normalized_job_id、audit_id、准确 readback_text；返回补证后的 job + meta | 仅支持已有历史声明，缺原审批/审计/准确回读继续待补证 |
| pipeline sync | PipelineSyncRequest：event_id、pipeline_id、candidate_id、expected_version；返回 job + meta | 不接受正文、快照或特征随填；来源变更或绑定失效时停止并重读 |
| pipeline list / form / history / due | list/form/due 用 candidate_id；history 用 pipeline_id + --candidate | candidate 不匹配不能读其他人的记录 |
| pipeline inspect / migrate / verify-migration / project / rollback | 见下一节 | 数量/身份不符或有后续事实时不能强行激活/回滚 |
| pipeline metrics / diagnose | 见指标节；返回不可变指标 ID、证据与诊断/持续观察原因 | 没有闭合窗口、可比切片或足够来源证据时保留未知/持续观察 |
| pipeline metric-show / diagnosis-show | 对应 ID + --candidate，回读持久事实 | 不凭显示过的临时结果推断已落库 |
| pipeline rule-propose / rule-confirm / confirmed-rules / rule-review / rule-show | 见规则节 | 提案和回滚提案都不等于本人批准 |

所有修改用稳定 event_id 和 expected_version。相同 ID、相同原始输入重放返回原结果；异文复用或版本落后会报错。原结果只代表该次调用，之后请 list/form 读取当前态。别通过不断换 ID 绕过拒绝。状态和证据在事务中落盘，失败不会留下半条当前态。

## 通用旧数据迁移与切换

1. 宿主固定代码 SHA，停止原写者与轮询，备份原队列、相关私有文件和数据库，checkpoint WAL。迁移是离线操作。
2. pipeline inspect PRIVATE_QUEUE 只显示形状与摘要。按真实字段写 PipelineMigrationConfig：migration_id、candidate_id、domain、expected_count、expected_row_ids、fields、salary_minimum_k/currency；历史发送行由 sent_row_ids 明确指定，不能从卡片决定猜发送。实际行数、原 ID 序列及优先级均由私有配置提供，公开仓库没有个人批次默认值。
3. job_id_mode=preserve 时按 job_id_prefixes 显式验证已有平台前缀并保留原 ID；platform_source_id 模式才从真实 source_job_id 组成平台前缀 ID。不按标题、公司或显示编号猜平台 ID。平台别名由 platform_values 显式配置。
4. 缺原 entered_at 时，只能使用私有配置中的 derived_entered_at 或 derived_entered_at_by_row 及 derived_evidence_reference。该时间标为 derived，不拿当前迁移时刻当旧入库时间；缺依据就停下补证。精确发送时间没有则继续 NULL，批次窗口不能代替。
5. 执行 pipeline migrate PRIVATE_QUEUE PRIVATE_CONFIG --database PRIVATE_DB。程序在私有库旁 pipeline-migration-backups 保存旧库与原文件字节，在临时库装配并校验，确认源文件/数据库未变化后才原子激活。
6. pipeline verify-migration MIGRATION_ID --candidate CAND_PRIVATE --database PRIVATE_DB。核对源 SHA、全部原 ID 与顺序、平台/岗位 ID/URL/title/company、实际建行、deferred 和 proof_pending。缺 URL 的条目留在有原行出处的 intake，标 partial/身份待核实，不生成虚假 listing 或 pipeline 行。
7. pipeline project MIGRATION_ID PRIVATE_PROJECTION --candidate CAND_PRIVATE --database PRIVATE_DB。投影按标准表单读取当前 pipeline，并保留原行映射；初始摘要均为 partial，jd_text/hash=NULL，不拼成全文。缺 URL 的原始行也必须在投影里找到。
8. 私有切换验收须逐条核对原配置的全部 ID、历史发送声明、带稿待决项、deferred 项与源 SHA；缺少、多出或目标不一致就保持暂停。不要把合成测试报告当这一步实跑日志。

旧卡片拒绝只保留决定，不自动变成岗位 abandoned。历史发送声明先保存可回查的入库/声明历史，当前可标 greeting_sent，但 meta.proof_status=proof_pending，sent_* 仍为 NULL。它不能推进已验证后段、自动超时或计入已验证发送转化。补齐原批准、发送审计和逐字回读后再 bind-send，不能临时造一份批准补账。

候选人的 pipeline authority 在临时库内准备，原子激活时才生效。之后旧 tracking 的写入与到期清单停用，旧记录只供历史读取；不能让两套当前态同时写。升级前已有跟踪记录时应先按离线迁移计划完整对账，再启动新 pipeline；只更新代码不代表已经完成切换。

需要回滚时先停止写者，执行 pipeline rollback MIGRATION_ID --candidate CAND_PRIVATE --database PRIVATE_DB。只有迁移后没有新增事实、当前摘要和旧库备份摘要一致才恢复。已有新观察、审批或规则后回滚会拒绝：保留新事实，交人制定恢复方案。不要删库、覆写源队列或直接改 authority 开关来绕过保护；不要把旧备份库与新 JSONL 双写。真实宿主恢复旧任务还需本人另行决定。

## 全文、特征和草稿同步

人工条目仍先走 intake enqueue / selection / resolve / next。旧host与新pipeline迁移统一使用 host backfill-plan / backfill-attach，传各自真实migration_id；同名时优先旧host来源，错误候选人直接拒绝。plan只读完整清单、私有优先ID及未知ID；缺URL等身份未确认项标identity_unverified，不能直接补采。对已确认岗位，按真实URL/provider建立或解析intake，backfill-attach复用原intake snapshot全文/身份/预算门禁，再同步同一候选人与岗位的pipeline。所有路径都必须有真实详情、身份、预算许可和抓取记录。新读取先预占 sourcing budget，失败/重复读取仍占额。搜索保留实际 query_hit；人工/推荐为 NULL，不补造查询。

只有真实 attach 历史与当前最新完整快照相符，pipeline sync 才写 jd_text/hash；只有实际 factorize/draft 历史才可带入特征和正文。scenario、tech、domain 来自原文因子化或实际 intake 私有政策，不能事后自由填写。当前 JD 改变时旧特征、草稿、复核、批次和计划按原链路失效；pipeline sync 清当前派生绑定，保留旧原文、已发全文和历史。

普通intake操作后仅自动同步已经显式绑定的pipeline。新迁移的backfill-attach还可在核对原行与真实intake的candidate/domain/platform/URL/provider后建立原先缺失的绑定；它追加旧原行SHA/v0到实际完整快照、观察时间与读取记录的谱系，保留原摘要，人工query_hit仍为NULL。若intake已提交而sync或谱系链接中断，原样重放同一事件可继续；已完成事件直接回放原结果，修改输入被拒绝。已废止轮次拒绝补采。接线不生成新发送、不替代门禁；宿主应核对sync/form及链接的实际返回，失败写入unfinished，不能把intake成功推断成表单已经更新。

实际 outreach batch 有对应 harness_version 且准确草稿绑定可复查时使用该版本，否则 CONTENT_<hash> 仅表示这段内容的版本，不能把每条内容摘要当成共享 harness 版本做因果归因。发送时的切片从真实请求快照冻结；后续改 JD 或简历版本不能改写历史发送的特征/版本。

## 累计指标与诊断顺序

先 metrics，保存原始 metric_id 与 evidence；再用这些原 ID diagnose。不要把 diagnose 生成的带诊断关联副本当成下一轮原始计算输入。metric-show 与 diagnosis-show 均按候选人回读。

PipelineMetricsComputeInput 包含 candidate_id、已闭合 UTC window_start/window_end、完整 scope、可选已确认 rule_id。窗口为 [start,end)，不可用开放“至今”。scope 固定七维：platform、domain、scenario、tech、greeting_version、resume_version、salary_band，对应 dimension_* 字段。dimension_platform=all 是明确平台汇总；其他 NULL 表示来源未知，不能当通配符。未知 harness、缺全文/因子化、缺版本的来源不会凭自由标签被补齐。

salary_band 是稳定统计分箱，按已验证 salary_max_k 划为 below18k、[18,25)k、[25,40)k、40k+；未知/不可比为 NULL。分箱边界不设个人薪资底线，实际薪资门禁仍使用私有条件并固定 upper_bound。

~~~json
{
  "candidate_id": "CAND_DEMO",
  "window_start": "2026-01-02T00:00:00Z",
  "window_end": "2026-01-03T00:00:00Z",
  "scope": {
    "dimension_platform": "boss",
    "dimension_domain": null,
    "dimension_scenario": null,
    "dimension_tech": null,
    "dimension_greeting_version": null,
    "dimension_resume_version": null,
    "dimension_salary_band": null
  },
  "rule_id": null
}
~~~

这是未知来源切片的合成格式示例，宿主应使用实际来源值，不能用这份空 scope 代表所有岗位。脚本只从实际数据库装配事实，不接受外填分子、分母或诊断比率。

- historical_rate：该段在当前窗口开始前的累计去重岗位 cohort，成功也只核算到窗口开始前。
- sliced_cumulative_rate：截至当前窗口结束前的累计同切片转化，作为诊断主依据。
- optimized_rate：指定本人已确认规则生效后进入该段的累计 cohort，成功核算到窗口末；无已确认规则为 NULL。
- window_rate：仅该窗口新进入段的 cohort 比率，只供参考。零分母为 NULL，不写 0 冒充观察结果。

主 numerator/denominator/sample_count 对应累计计数；历史、优化、单窗口各自计数与原岗位引用在 evidence 回读。按真实平台岗位去重，选该段首次 source 的同一联系轮次计 destination，不把新轮回复算给旧轮。废止岗位保留在累计分母中，不能通过删行抬高比率；关闭、拒绝、硬条件不符及待补证等原因另列。重复计算不把已有累计窗口行再次相加。

漏斗的每个相邻段都计算，并额外计算 greeting_sent→initial_contact、greeting_sent→interviewed。resume_sent→interview_pending 已是相邻段，不重复生成一份指标。

PipelineStoredDiagnosisInput 用 candidate_id、current_metric_ids、previous_metric_ids、exclusions_reviewed、review_reference、可选 rule_id。只有真的复核过混杂原因才设 exclusions_reviewed=true，并保存原始 review_reference；不能为让诊断通过填个 true。前一相邻闭合累计窗口和当前累计窗口共同验证持续下跌；缺历史、缺伴随段、窗口不连贯、未排除混杂或处于边界抖动时输出 observation_reasons，保持持续观察。没有绝对样本数门槛，分子/分母只用于校核比率和来源完整性。

比较采用切片累计比率 < historical_rate × 0.8。已读段低而已读后建联段正常时优先 funnel_blocked_at_read，不能直接归因招呼语内容。招呼语段持续下跌且简历段无同等下跌才可归 greeting_issue；简历段下跌且发送→建联段正常才可归 resume_issue。规则生效后 optimized_rate 同时高于历史比率和生效前累计比率才为 optimization_effective，否则为 optimization_ineffective。单窗口起伏和绝对发送数不能证明优化有效。

## 提案、确认与回滚提案

pipeline rule-propose 采用 PipelineRuleProposalInput：proposal_id、candidate_id、diagnosis_id、diagnosis_digest、category、rule_text_after，以及可选 previous_proposal_id/rule_text_before。必须绑定当前持久诊断及原累计证据，改前规则须匹配当前已确认规则。返回准确 rule_hash、scope、前后效果与待本人确认状态。

向本人展示准确范围和全文后，pipeline rule-confirm 提交 confirmation_id、proposal_id、candidate_id、原样 rule_hash、accepted、owner_text、owner_reference。该 hash 绑定提案效果与范围，不能自己只算正文摘要代替。证据或已确认范围状态改变时重新评估；已有文案 Accept、岗位 like 或其他任务授权不能替代规则确认。

pipeline confirmed-rules 只返回当前候选人的有效已确认规则；生成前进一步核对 scope 适用性，记录规则 ID/摘要。规则不覆盖已确认证据、独立复核、正文审批或发送许可。没有本人另行放行的自动生效路径；未确认假设不进入规则、词库权重或查询计划。

下一窗口用真实 rule_id 再 metrics / diagnose，再 pipeline rule-review 提交 review_id、candidate_id、rule_id、诊断 ID 与准确 digest。优化无效时 review 只追加回滚提案，rules_changed=false；实际撤回/恢复仍需本人确认该回滚提案。不要把 review 当成已完成回滚。rule-show 回读完整效果，原提案、确认、复核与撤回历史均保留。

普通初稿/最终稿 diff 仍用 host message-diff / diff-report / rule-propose / rule-confirm。其独立岗位成熟度是文案观察机制；不能拿这个样本阈值限制 pipeline 累计比率诊断，两者来源和提案依据分别校验。

## 宿主两轮验收模板

每轮先写私有计划，结束后填真实证据并调用 host round-report；用 host round-show 回读，不写默认成功。host round-template 提供待填结构，删除 template_only 并填实际数据后才作为输入。unknown 继续 NULL，零新增有真实证据才写 0。

| 私有记录项 | 本轮必须保存 |
|---|---|
| 版本与恢复 | 代码 SHA、candidate/domain、真实任务 ID/时区/下轮时间、单实例锁、恢复检查点 |
| 搜索 | CombinationPlan/claim、实际 ordered_queries、成功查询/失败预算、真实 query_hit、去重数与过滤原因引用 |
| 结果 | 新入库数、新稿数、完整性、词库版本、未执行查询与未完成项 |
| Pipeline | form 对账、原ID/声明/待补证/deferred清单、真实状态变化、静默截止点、暂停、各态数量、新废止数/原因 |
| 页面 | 两站分别 messages/search 的 logged_in/login_redirect/not_loaded，实际截图/回执、重载与需本人操作项 |
| 飞轮 | 原始 metric IDs、窗口/七维 scope、三个累计比率和计数、排除原因、诊断或持续观察、规则确认/复核状态 |
| 真实验收 | 私有数据校验日志、状态重读、通知送达与单实例恢复；尚未实际执行标 unverified |

两轮先后各保存独立报告，HostTwoRoundInput填写 candidate_id、first_report_id、second_report_id，调用 host verify-rounds。合成执行、一轮重放或缺少来源不能冒充两轮。real_browser_verified=false 保留，由 Muse 提供真实回执并交本人核验。

切换首轮若源 SHA、原 ID 集合、目标、声明、草稿或 deferred 项不一致，保持暂停并按上述受保护回滚处理；不能为了恢复旧 JSONL 队列而丢掉新数据库事实。真实数据切换、任务编辑和外部通知均由宿主在本人授权后另行执行。

## 仓库验证与范围

代码提交前运行 pytest、Ruff、strict mypy、git diff --check，并核对跨域合成流程、活动政策与隐私扫描。测试日志说明代码结果；真实迁移、网站、任务和通知验收需单列实际证据。换域只换私有 candidate/domain、已确认证据、硬条件、基础查询、当前域词库、字段映射与本人规则，不改 schema、状态机、预算或审批核心。

旧桥接删除仍是独立计划，本工程没有新增本地浏览器/MCP/飞书控制链。按需从 [pipeline技能参考](../skills/job-hunting/references/pipeline.md) 加载当前阶段，不一次读取整棵技能树或所有私人原文。

## 同岗新联系轮次与既有回复

旧轮次已废止且本人明确要求重新联系时，`pipeline create` 建立新的 `contact_round`。已有首招审计的岗位仍走原 conversation 回复流程，不能重新走首招审批规避重复联系门禁。

`pipeline bind-reply <private.json> --database <private.sqlite3>` 的类型化输入为 `PipelineBindReplyInput`：`event_id`、`candidate_id`、`pipeline_id`、`expected_version`、`conversation_id`、`approval_event_id`。仅允许后续轮次的 `draft_pending`；从已有、晚于本轮入库的 `REPLY_APPROVED` 读取准确 `FOLLOW_UP` 或 `ANSWER` 正文、摘要和实际 harness 版本，并验证原 ask、审批原话、序列锚点、岗位身份及 URL。首轮、简历回复、关闭/拒绝会话、缺原问题、审批后出现新消息或换附件均拒绝。缺完整 JD 仍按 partial 保存，接口不补造正文。

绑定只追加产物来源和不可变请求快照，状态保持 `draft_pending`；相同事件原样重放返回原结果，不创建审批、租约、发送或定时任务。Conversation 本身没有候选人字段，此处依赖当前候选人拥有的 pipeline、准确 normalized job/URL 及同一私有数据库关系，不能宣称认证了自然人身份。

实际回复仍由原 `conversations ask-reply / approve-reply / reply-gate / record-reply` 门禁和宿主执行。拿到对应成功 `REPLY_RESULT` 后，再调用原 `pipeline transition` 到 `greeting_sent`，`conversation_id` 必须对应已绑定来源，`send_reference` 与 `evidence_reference` 均填实际结果 ID，`readback_text` 必须逐字对应本轮获批正文。成功时间来自原结果，不能用登记时间替代。旧轮结果、未绑定回复或重复消费的发送引用不得推进；回读不一致暂停原状态，需本人恢复，不能重发补救。

`pipeline sync` 保留已绑定回复，避免旧 intake 首招覆盖。待发送期间 JD 快照或正文来源变化时，清除派生回复及其绑定、暂停并交本人重新确认；原审批与历史仍保留，不静默继承旧正文。