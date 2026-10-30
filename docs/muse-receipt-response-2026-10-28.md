# Muse 回执：历史交付与当前执行边界

本页记录此前PR #5、#6、#7分阶段交付的职责，当前后段执行以 [pipeline飞轮协议](pipeline-flywheel.md) 为准。原私有队列的大小、原始编号、实际发送声明、求职条件、时间与字段映射均由宿主私有配置提供，不作为公开代码或文档的默认批次。

| 回执项 | 公开核心与当前接线 | 仍需宿主实际验收 |
|---|---|---|
| 人工加岗/旧队列 | 三入口、CAS恢复、备份、显式映射、精确原ID校验、投影和保护回滚；后段切换另走pipeline migrate | 用实际私有配置对账全部原ID/链接，接入真实聊天/卡片/轮询 |
| 历史发送声明 | 保留原证据门禁；声明与已验证发送分开，未补证为proof_pending；候选人authority启用后旧tracking只读 | 逐条核对原审批、正文、实际审计与准确回读，缺时间不造时钟、不凭批次窗口补时间 |
| 薪资/预算 | 显式upper_bound及私有底线/币种；conservative默认与显式扩展档分别冻结，来源会话/间隔/风控保留 | 核对实际调用参数、真实预算回执和本人条件，不把公开示例当个人配置 |
| 全文回填 | 私有优先ID清单、真实观察/预算、legacy摘要到全文谱系、JD变化派生失效；绑定pipeline后sync | 从真实详情补全文，搜索保留真实query_hit，人工/推荐留NULL；缺全文仍partial |
| 文案diff与规则 | 六类位置证据、全文hash、独立岗位观察成熟度、恢复原稿排除、逐条本人确认/撤回 | 原始前后稿和分类证据留私有区，不倒推编造初稿，不用文案Accept代替规则确认 |
| 后段累计飞轮 | 标准九态表单、48小时证据时钟、闭合累计指标/诊断、scope与本人规则复核 | 对真实状态/窗口/排除原因逐项复核；review无效只产生待确认回滚提案 |
| 两轮验收 | host round-template/report/show/verify-rounds及pipeline统一状态汇总 | 真实网页、私有重读、单实例恢复、实际通知送达；real_browser_verified仍false |

未确认假设没有进入生成规则、词库权重或查询计划。文案对比不证明已发送，人工选择、岗位偏好和文案反馈分开；学习信号不替代候选人证据确认、正文/附件逐项审批与发送许可。

物理事实源是宿主私有SQLite。JD/发现/特征、旧原始行、回填谱系、intake和消息diff各保留来源；pipeline_jobs是已切换候选人的后段当前态，统一pipeline_job_form读取表单，history/requests/observations保留追加证据。累计指标、诊断、规则和本人确认同样可回查。JSONL/MD是投影，不作为第二套写入权威。

旧intake迁移备份与pipeline切换备份分别保存manifest，不混用回滚。回滚仅在无后续事实、当前与备份摘要一致时允许；已有新观察、批准或规则后保留事实并交人处理，不能强行用旧队列覆盖。

换域只替换私有candidate/domain、已确认证据、硬条件、基础查询、当前域词库、实际映射与本人适用规则；设计域合成用例验证可复用流程，不改schema、状态机、预算或审批核心。

按需阅读 [宿主接线](../skills/job-hunting/references/muse-host-adoption.md)、[回填与差异](../skills/job-hunting/references/muse-backfill-and-diff.md) 和 [pipeline参考](../skills/job-hunting/references/pipeline.md)。桥接仍只有 [独立删除计划](muse-bridge-removal-plan.md)，未在本工程删除。私人批次资料不贴入公开PR，也不重写历史Git提交。

此前代码验证记录：P0为998 passed，P1为1021 passed；当时Ruff、strict mypy和diff检查通过。它们是 [PR #5](https://github.com/Joshuazhang99662200/full-stack-ai-jobagent/pull/5)、[PR #6](https://github.com/Joshuazhang99662200/full-stack-ai-jobagent/pull/6)、[PR #7](https://github.com/Joshuazhang99662200/full-stack-ai-jobagent/pull/7) 的历史交付证据，不代表当前后段工程的最终门禁结果或宿主实跑结果；本轮实际测试日志另附。

本工程未改写运行中的Muse任务、未访问招聘网站、未发送消息/附件、未创建任务、未送达通知。真实数据迁移、切换与连续两轮验收均保持unverified，须宿主在本人另行授权后执行；不能把合成测试通过标成真实验收完成。
