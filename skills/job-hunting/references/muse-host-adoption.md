# Muse 宿主接线与验收

此协议用于 PR #5 之后的既有私有队列接入。只加载当前步骤；数据库是事实源，JSONL/Markdown 是投影。CLI 不打开浏览器、不发消息、不设置定时任务。所有路径均指宿主自己的私有目录。

## 显式读取预算

默认 conservative 仍为每站每轮 3 查询、20 详情尝试、每日 50。扩展档必须在 SourcingRunRequest 同时写入 budget_profile=muse-expanded-v1、query_limit=12、detail_limit=60、daily_detail_cap=240，不能只增加提示词。组合与 intake strategy 输入也必须显式传相同 budget_profile、query_limit；plan/run 档位不一致拒绝领取。扩展档允许 8–12 查询，宿主按需要明确填写；显式 detail_limit=20 就只允许 20，程序不会补到 60。

~~~json
{"budget_profile":"muse-expanded-v1","query_limit":12,"detail_limit":60,"daily_detail_cap":240}
~~~

以上只是需要合入原有请求的预算字段，candidate_id/source/run_id 等仍按同版本契约填写。先执行 jobs sourcing-budget --budget-profile muse-expanded-v1 --daily-detail-cap 240，再 sourcing-start；每次实际操作前 reserve，allowed=true 才读取，随后 result。每查询最多处理前 10 条列表，先跨查询去重再分配详情。失败、取消、重复详情仍占额，60/轮与240/站/日都到顶即停。计量仅覆盖同一私有数据库，不能跨数据库另开额度。

扩展只改变读取计数，来源 URL、每会话总页数、翻页间隔、风控停止与本人限额仍有效。需要更多查询时按来源会话约束分轮恢复，不能以扩展预算绕开会话限制。来源清单的 max_detail_reads_per_day 是 conservative 默认；只有显式扩展档允许上述覆盖。发送预算完全独立。

薪资输入显式使用 compensation_comparison=upper_bound：底线18k时15–25k、14–18k通过，13–17k拒绝；币种、计薪周期或区间未知保持 REVIEW。

## 旧队列离线迁移

1. 固定相同代码版本，停止全部数据库写者并 checkpoint WAL。保留原 queue.jsonl、已发原文件与数据库；不要在线迁移。
2. host inspect-queue PRIVATE_QUEUE 只查看字段形状。按实际字段编写 QueueMigrationConfig；不猜字段含义。设置 migration_id、candidate_id、domain、expected_count=40、fields 映射；平台别名用 platform_values 显式映射。40是本批次验收值，其他批次须明确修改。
3. 已发信息可以在队列中，也可传 --sent-file PRIVATE_SENT_JSONL。独立文件用 sent_row_id_field 对应队列原ID、sent_send_reference_field 对应原发送引用，expected_sent_count=8 校验本批数量；缺时间保持空值或原窗口文本。没有独立文件时用 sent_row_ids 明确标出原记录。
4. host migrate-queue PRIVATE_QUEUE PRIVATE_CONFIG --sent-file PRIVATE_SENT_JSONL --database PRIVATE_DB。临时库验证通过后才原子替换，原文件字节副本与旧库保存在私有库旁 migration-backups。数量不符、重复ID、候选人不符、错误链接或输入变化均拒绝。默认要求40个不同岗位根；确认原数据重复岗位时才能显式 require_distinct_jobs=false，仍保存40行原ID映射。
5. host verify-migration MIGRATION_ID --database PRIVATE_DB，核对原ID、原行摘要、目标链接、40行/岗位根、partial及待补证发送。重放同一输入幂等，换输入须新迁移ID。
6. host project-queue MIGRATION_ID PRIVATE_PROJECTION --database PRIVATE_DB，回读私有投影。未知时间仍为 null，不能拿迁移时间当采集时间。旧摘要固定 legacy v0/full_jd_text_stored=false；snapshot_pending，未进策略。完整JD之后通过正常快照链追加，原摘要保留。正文不全不起草、不因子化、不学词库。
7. host rollback-migration 仅允许迁移后尚无其他活动且备份摘要一致时恢复；之后已有新事实必须保留，不能强行回滚覆盖。

迁移不会把旧状态字符串转换为审批或实际发送。每条旧已发默认 proof_pending。只有已有正式审批、准确获批正文、实际发送审计及回读证据，才执行原 tracking start；历史迟登记必须给未来 next_poll_at，保存 registered_at、missed_check_days，检查次数仍从0开始。不能把失去的1/3/7/14天机会计为已查。再用 host bind-tracking 的 LegacyTrackingBinding 绑定原发送引用与实际tracking。缺确切时间/原文/审计则继续待补证；8条声明不等于8条正式跟踪。原批次时间窗口端点不能充当逐条精确发送时间。

## 登录、未加载与通知

每站分别记录 messages/search，调用 host page-observe：state为logged_in、login_redirect、not_loaded之一，含真实 observed_at/evidence_reference。not_loaded只允许一次 reload_once；再次未加载保持 unconfirmed，不能记无回复。登录跳转立即 request_user_login/notification_required，即使静默时段也必须由宿主实际告知本人。CLI只输出要求，不负责送达通知。

消息页跳转暂停同站活跃tracking；搜索页跳转不推断消息页状态，须追加实际 sourcing gate。另一站保持独立。本人完成登录后重新读消息页，明确恢复跟踪；不能自行换账号、重试风控或把 logged_in 当回复证据。

## 轮末与两轮验收

每轮调用 host round-template CANDIDATE DOMAIN 取得空模板，填实际开始/结束、run_ids及证据后删除 template_only，再 round-report。未知计数保持 null；去重数、过滤原因必须附原始宿主证据。程序按本轮实际执行查询核对 query_hit，并扫描本轮该来源所有发现，漏传ID不能提高归因比例。手工/推荐单列，不伪造查询。

报告分开记录查询、详情、去重/过滤、完整快照、新入库/草稿、词库版本、旧partial、跟踪待查/漏查/待补证、登录与unfinished。零新增也保存并按通知设置给轮末摘要。再次读取 round-show 验证持久化；两轮按实际先后提交 verify-rounds。重复报告不能算两轮。

报告的 real_browser_verified 始终为 false：合成演练和程序一致性不能证明真实 Muse 网页已接通。Muse须附两轮真实宿主回执与未完成项，由本人核验；不得把 mock 输出写成真实零新增、真实40迁移或真实8跟踪通过。仓库不会设置或改写运行中的 Muse 任务。

## 实际宿主调用检查点

入口明细见 [人工加岗协议](manual-job-intake.md)。聊天URL用entry_kind=url；消息列表编号用list_item + 不可变list_version；消息卡片用conversation_card及原message_reference，未解析身份先selection固定映射。三种入口都先intake enqueue，成功后才能打开详情/起草；重复request_id同文重放不增样本，异文报错。同岗多来源经resolve合并且保留出处；只有真实JobListing可先绑定，不能造占位JD。

每次交互/轮询开始 intake list CANDIDATE DOMAIN --database PRIVATE_DB；对未完成项 intake next INTAKE_ID --candidate CANDIDATE --database PRIVATE_DB。按next给出的expected_version推进一步，再next重读；snapshot_pending不能起草或学习。完成全文/特征后 intake strategy PRIVATE_STRATEGY PRIVATE_LEXICON --database PRIVATE_DB，下一轮每站sourcing-start后用intake claim领取同域活跃计划。组合不等于搜索成功；实际sourcing query的complete之后才能intake record-search PRIVATE_EXECUTION，必须显式new_count，0也明确写0，失败或登录跳转不写成功。所有调用均同一私有库；queue/MD只从程序状态导出。

轮询先处理page-observe，再tracking due CANDIDATE --database PRIVATE_DB，只检查返回的未暂停awaiting_reply。实际观察后tracking event保存no_reply/suspected_reply/reply_confirmed等；仅徽标变化只能疑似，明确对方新消息后才确认。登录跳转暂停并要求立即通知，恢复须本人原话；closed不再到期，不能恢复终态或单轮凑四次。轮末tracking report与host round-report回读，附各状态数量、下查时间、漏查与新增放弃原因。若核心或私有持久化不可用，就停止在草稿/待核实，不创建替代本机服务。
