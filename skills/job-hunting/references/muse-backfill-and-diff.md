# Muse 全文回填与招呼差异

按需加载：补旧队列全文读第一节；采集本人编辑/恢复稿读第二节；生成时仅读取本人已确认规则。依赖 [宿主接线](muse-host-adoption.md) 的同版本私有数据库。全文、差异与本人原话只能保存在 .jobagent/ 或 candidate/private/，不能进入公共仓库或PR。

## 旧岗位回填

以下host backfill接口同时支持旧host迁移和新pipeline迁移的真实migration_id；同名时优先旧host来源，错误候选人直接拒绝。plan只读完整清单、私有优先ID和未知ID；缺URL等身份未确认项标identity_unverified，先确认身份。已确认条目以真实URL/provider建立或解析intake，attach核对原行身份，通过完整JD预算门禁后同步pipeline并追加谱系。两条路径都保留原摘要及来源，无需伪造另一种迁移记录。

优先级和原始ID由宿主按实际待决草稿保存在私有配置，公开算法不固定任何人的队列编号：

~~~text
jobagent host backfill-plan MIGRATION_ID --candidate CAND_PRIVATE --priority ROW_DEMO_A,ROW_DEMO_B --database PRIVATE_DB
~~~

清单列出全部原ID、真实链接、平台ID、intake_id、expected_version、legacy_snapshot_id/v0、当前完整性；未知优先ID单列待核实。未回填保持 partial_not_in_strategy（partial，未进策略），旧稿不代表已有完整JD或可复用批准。清单只读，不推进状态。

对每条先核对平台与岗位身份；未知采集时间不能拿迁移时间替代。按来源会话/间隔及预算预占，宿主读取真实详情页全文。保存真实抓取时间与发现归因：实际搜索保留真实query_hit；人工/推荐来源query_hit=null，不编造查询。正常导入更新 normalized job，并用 jobs snapshot 保存原文及发现记录；列表要点不能改标全文。

IntakeSnapshot新增可选 observation_id，指向本次真实发现。内容未变时复用同一snapshot版本，预算窗口按该发现的 fetched_at 校验；不能用旧观察消费新读取许可。新抓取必须有已完成、同候选人/平台/岗位/链接的detail attempt。旧缓存路径仍沿用既有校验。

编写私有 LegacyBackfillBinding：migration_id、row_id、candidate_id；snapshot内含 event_id、intake_id、candidate_id、expected_version、snapshot_id、observation_id、attempt_id。调用 host backfill-attach PRIVATE_BINDING --database PRIVATE_DB。核心全文/身份/预算门禁通过后，新pipeline路径先同步实际产物，再追加legacy v0 → 正式完整快照的谱系链接，回读输出中的时间、URL、原文摘要和归因。人工query_hit保持NULL。若intake已提交但后续同步或链接中断，原样重放同一event_id续接；完整事件仅返回原结果，改变输入被拒绝；已废止轮次不能补采。原未知时间的v0保留在legacy表；第一个正式全文版本为v1，不伪造有时间的旧JD快照。后续原文改变追加v2及以上，旧原文不覆盖；synchronize使旧特征、草稿、复核、批次和计划绑定失效，再按新全文处理。

回填不会自动学习或起草；继续既有 intake factorize/submit-draft/review/strategy。明确岗位兴趣仍由既有 user_added 记录一次；只有文案Accept不增加岗位正例。

## 初稿与最终稿比较

私有 MessageDiffInput 提供 event_id、candidate_id、job_id、同一稿件的 draft_reference、真实 occurred_at、source_reference、initial_text/final_text以及两份精确UTF-8全文SHA256（sha256:前缀）。初稿在同一episode内不可变；最终稿可通过新事件追加。输入最终文本可来自本人编辑或历史发出稿证据，但diff记录本身不证明已发送，send_proof_verified始终false；正式发送仍依赖现有审批/回读审计。缺初稿时列为未完成，不倒推编造初稿。

host message-diff PRIVATE_COMPARISON --database PRIVATE_DB 返回变化位置与类别。六类：fact_correction事实纠偏、job_routing岗位路由、business_specificity业务具体化、technical_accuracy技术准确性、style风格、motivation动机。

仅标点/空白变化可以自动归style。其他语义由宿主或本人给 labels 分类提案，每项必须含category、initial_start/initial_end、final_start/final_end（Python字符偏移，左闭右开）及classifier_reference；位置须实际命中变化，不能拿未变的句子当依据。可多类；缺分类保留needs_classification，不猜事实或动机。分类证据证明文本有变化，不证明分类判断已经本人确认。

human_picked、job_preference、message_feedback是三个独立字段。它们不互相推断，不更新SearchSignal、词库或查询计划。明确挑岗参与搜索仍走原intake兴趣接口；human_picked只作来源/选择元数据，不再加一份同义奖励。

同一event重放不重复采样。重复岗位不增加独立岗位数；同一稿件以真实时间最新最终稿为准（同时间按追加顺序），卡片恢复初稿时追加initial==final、labels=[]的新事件，得到无变化，排除中间编辑。勿把旧编辑事件重新追加成最新一次本人选择。

host diff-report CAND_PRIVATE --database PRIVATE_DB 给出每类不同岗位数、observed_once（1）、repeated（2）、stable（>=3）、未知分类与评估候选。0条为none；3个不同岗位只进入评估报告，不自动调权重、拉黑、改生成规则或查询。

## 本人确认后落盘

1. 从最新评估报告取得report_digest；宿主展示支持样本与适用范围，提出一条准确rule_text。MessageRuleProposal包含proposal_id、candidate_id、category、rule_text、report_digest。host rule-propose PRIVATE_PROPOSAL --database PRIVATE_DB 只有该类>=3个不同岗位才接受，返回rule_hash与awaiting_owner_confirmation。
2. 向本人展示准确规则全文和范围，取得逐条原话。MessageRuleConfirmation填写confirmation_id、proposal_id、candidate_id、rule_hash、accepted、owner_text、owner_reference，调用host rule-confirm。正文摘要、候选人或评估版本不匹配就拒绝；已有文案Accept不能充当本次规则确认。accepted=false可明确撤回规则。
3. 生成前 host confirmed-rules CAND_PRIVATE --database PRIVATE_DB，只按当前岗位适用范围加载本人已确认的具体规则，保存规则ID/摘要到私有上下文。默认空列表。规则不覆盖事实/完整JD/独立复核/逐项审批；程序没有向生成器自动注入推断。

A/B/C是假设占位，仓库没有预置它们的内容，也没有导入为生成规则、词库权重或查询计划。若本人日后确认，按上述接口逐条落盘；不能只把草案重命名为“已确认”。

## 两轮宿主复核

先回读迁移投影与backfill-plan，确认缺全文仍partial；在两轮真实任务分别保留plan/claim、actual query执行、读取预算、归因、去重/过滤、版本和tracking/page报告。用P0的round-report/verify-rounds核对，另由本人检查真实网页、单实例恢复、通知及私有状态重读。代码合成通过不替代这些真实回执。


## 与后段 Pipeline 对接

已切换候选人的后段状态以pipeline_jobs为准，旧tracking只读。真实intake snapshot/factorize/draft/batch改变后，对已绑定行使用pipeline sync并回读form；sync只从当前已验证完整绑定和持久历史读取，不接受自由正文/特征。JD变化清旧派生，已发送原文与审计保留。缺身份仍留intake；单纯同步不新建发送或解除审批。操作顺序和失败处理见 [pipeline](pipeline.md)。

普通diff的独立岗位成熟度只服务文案观察提案；后段pipeline的累计比率诊断不设绝对样本数门槛，走pipeline metrics→diagnose→rule-propose→本人rule-confirm。两种提案来源分别校验，不把“文案Accept”当规则批准或岗位like。pipeline规则确认使用提案返回的完整效果rule_hash，不用普通正文hash替代。

生成前读取当前候选人的有效confirmed-rules并检查scope，NULL来源不代表通配范围。CONTENT_仅内容版本，不能当共享harness版本做比较。pipeline rule-review无效时只生成待确认回滚提案，不自行应用。真实任务未切换、网站未访问、消息未发送、通知未送达；两轮验收仍unverified且real_browser_verified=false。
