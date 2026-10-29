# Muse 私有状态接入与轮末验收

只加载本页当前需要的步骤。候选人、真实行数/原ID、优先级、来源时间、字段映射、岗位正文与个人条件均由宿主私有配置提供。数据库是事实源，JSONL/MD是投影；公开仓库不预置任何人的批次或账号。

后段状态切换使用 [pipeline协议](pipeline.md) 及 [完整工程说明](../../../docs/pipeline-flywheel.md)。原 host inspect-queue / migrate-queue / verify-migration / project-queue / rollback-migration 仍用于旧intake数据接入，不能当成新pipeline authority切换已经完成；不要混用两种迁移的manifest或回滚备份。

## 显式读取预算与薪资

conservative默认每站每轮3查询、20详情尝试、每日50。扩展档SourcingRunRequest必须同时显式传budget_profile=muse-expanded-v1、query_limit、detail_limit、daily_detail_cap；例如受支持的12/60/240档。组合和intake strategy同步传相同profile/query_limit，档位不一致拒绝。显式20详情仍只允许20，不自动升额。

~~~json
{"budget_profile":"muse-expanded-v1","query_limit":12,"detail_limit":60,"daily_detail_cap":240}
~~~

这是预算字段示例，仍须合入真实run/candidate/source输入。先jobs sourcing-budget核对，再sourcing-start冻结；每次实际操作前reserve，allowed=true才读取，随后result。每查询最多前10条列表，先跨查询去重再分详情；失败、取消、重复读取都占额。轮/日额度耗尽停止后续操作，不换ID、数据库或账号另开额度。来源URL、会话总页数、翻页间隔、风控停止与本人更严格的限额继续有效。发送预算独立。

薪资比较显式compensation_comparison=upper_bound，底线和币种来自本人私有条件。区间上限能达到底线才通过，未知或币种/周期不可比保持REVIEW。统计薪资分箱不替代个人筛选条件。

## 离线接入检查点

固定SHA并停写/停旧轮询，先inspect字段形状，再填写私有配置。expected_count和expected_row_ids必须由实际原文件核对，缺行、多行、重编号、错身份均停止。旧队列源文件保留字节和SHA；实际入库时间未知时只接受有私有依据的derived时间，不能用迁移时刻冒充。

新后段入口按顺序运行：

~~~text
jobagent pipeline inspect PRIVATE_QUEUE
jobagent pipeline migrate PRIVATE_QUEUE PRIVATE_CONFIG --database PRIVATE_DB
jobagent pipeline verify-migration MIGRATION_ID --candidate CAND_PRIVATE --database PRIVATE_DB
jobagent pipeline project MIGRATION_ID PRIVATE_PROJECTION --candidate CAND_PRIVATE --database PRIVATE_DB
~~~

程序备份原库与源文件，在临时库验证后原子激活。缺URL或身份的条目仍保留原行出处与待处理intake，不造JD/岗位行。旧摘要为partial，完整JD/hash为NULL；卡片拒绝不映射岗位废止。历史发送声明为greeting_sent/proof_pending，准确发送字段为NULL，不能当已验证发送或拿批次窗口补时间。

已有原审批、sent审计、准确回读和真实目标后用pipeline bind-send补证。切换后以pipeline_jobs为后段权威，旧tracking只读且不再到期写入；不要再用tracking start/event写第二套当前态。

回滚用pipeline rollback MIGRATION_ID --candidate CAND_PRIVATE，仅在无后续事实、库与备份摘要一致时可恢复。之后有新事实就保留并交人处理，不能强行覆盖队列或修改authority开关。实际宿主切换、恢复旧任务需要本人另行决定。

## 聊天、轮询与登录接线

三入口按 [人工加岗](manual-job-intake.md)：URL用url，编号用list_item+不可变list_version，卡片用conversation_card及原message_reference。先intake enqueue，未知目标先selection/resolve，不等文案Accept才入队；inspect/draft不隐式变like。

每次交互/轮询先intake list，再逐项next，成功一步重读当前版本；缺全文不能起草/学习。完整JD/因子化后intake strategy，实际轮次sourcing-start后claim。成功query的complete结果才record-search，new_count必须明确为真实值；失败、登录跳转和计划不能记成功。已绑定pipeline的产物变化后核对pipeline sync与form，不能把intake成功推断成表单已同步。

每站分别对messages/search调用host page-observe，state仅logged_in/login_redirect/not_loaded，含真实observed_at与evidence_reference。未加载最多建议一次重载，仍未加载保留未确认，不能报无回复。登录跳转立即要求本人操作并通知，静默偏好不覆盖阻塞通知。消息页失效暂停同站后段记录；搜索失效不推断消息页，须记录实际sourcing gate。通知送达由宿主执行，CLI只给要求。

pipeline due后先真实读对话，再observe；未读数只能疑似，新消息先conversations inbound再引用确认。唯一48小时静默时钟见pipeline页。恢复须本人原话，终态不复活；规则、学习与定时都不代表发送批准。

## 每轮报告与两轮真实验收

host round-template生成待填结构，填实际started/completed、run_ids、原查询/人工发现ID、去重数、过滤原因及证据、实际下轮时间与unfinished，删除template_only后才提交round-report。未知值保留NULL，0必须有真实观察。

报告保存组合清单、实际查询/详情、query_hit归因、去重/过滤、新入库/新稿、词库版本、partial、pipeline各态/待补证/截止点/新增废止原因、分站分页面登录状态和未完成项。手工/推荐单列，不能伪造query_hit凑完整率；漏传搜索发现ID也不能提高归因。旧tracking只作为未切换候选人的历史口径，不能与新authority的当前态相加。

用round-show回读持久结果，两轮独立、顺序真实、同候选人/域后用verify-rounds。real_browser_verified=false保持不变；Muse需附真实网页、私有状态恢复、单实例、通知送达和原文件对账证据，由本人复核。代码或合成演练通过不等于真实迁移或两轮验收通过。

本工程未改写运行中的Muse任务、未访问招聘网站、未发送消息、未创建任务、未送达通知；相关真实结果均为unverified。
