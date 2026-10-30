# 人工加岗闭环交付（2026-10-28）

基于已合并PR4的main c7352a1，新分支codex/muse-manual-job-intake。用户已批准持久队列和既有2/3成熟度规则。

## 已补齐的闭环

人工URL/编号/卡片先入队 → 真实listing或缓存岗位身份 → 预算内读取完整JD并绑定快照 → 两个独立分支：
- 宿主全文起草 → 原文/证据/硬条件校验 → 独立复核 → 绑定既有outreach批次 → 原审批/租约/发送链。
- 确定性/模型提案因子化 → 明确兴趣记user_added → 汇总本域新旧样本 → 保存版本MD与CombinationPlan → 下一轮领取固定计划 → 实际查询完成后写执行归因与轮换历史。

inspect/仅起草不会隐式变成喜欢；Accept文案不会奖励岗位方向。2个独立公司可探索，3个stable。重复消息/同岗多入口不增加独立样本，单正例不会立即置顶。

全新岗位不要求先伪造JD入库：IntakeResolve可直接绑定JobListing，完整JD到达后再绑定正式JOB_*。列表编号必须匹配持久不可变版本，不能把上一轮35错当这轮35。新URL与卡片可在首次读JD前合并。

## 实现映射

| 职责 | 文件 |
|---|---|
| 类型权威与输入 | src/jobagent/schemas/job_intake.py |
| 稳定目标键、双分支待办与安全状态视图 | src/jobagent/jobs/job_intake.py |
| 原子入队、CAS版本、事件和原始兴趣记录 | src/jobagent/storage/job_intake_repository.py |
| 真实身份、完整快照/预算、因子化与恢复 | src/jobagent/storage/job_intake_service.py |
| 草稿、硬筛、证据与独立复核、现有批次绑定 | src/jobagent/storage/intake_drafting.py |
| 域重算、活跃策略、领取与执行归因 | src/jobagent/storage/intake_strategy.py |
| 18项可调用宿主命令与按需上下文 | src/jobagent/cli/job_intake.py |
| 追加迁移 | src/jobagent/storage/migrations/0018_job_intake.sql |
| Muse交互操作协议 | skills/job-hunting/references/manual-job-intake.md |

原outreach、applications、candidate、conversations与bridge的生产实现保持不变。新入口调用现有规则，不新增发送通路或通用ReAct框架依赖。

## 恢复与一致性

消息先落库，再做外部动作；next返回稳定action_id、当前expected_version和实际输入契约。重复操作同号同文返回旧结果，异文/过期版本拒绝。中断在入队之后，下一次synchronize可补记未完成兴趣信号；迟到旧消息不覆盖较新选择。

JD变化后status/next/list/strategy自动退回待全文状态，清除旧特征/草稿/复核/批次/计划引用，保留历史。已联系岗位改走对话，不生成重复首招。原批准仍由既有摘要门禁处理，队列不批准、不撤销原审计。

MD、计划与队列引用在事务中激活；生成后、激活前中断只留不可变未激活版本，旧活跃指针完整。一次新增岗位不会抹掉旧样本：
- 本域既有队列样本自动汇总。
- 既有MD的snapshot_ids或strategy输入snapshot_ids可迁入以前选中的域快照，当前完整特征校验后保留。
- historical_learning可消费原SearchLearningRequest里的真实L1原话；同ID异文拒绝，首次迁入后继续保留，不能把旧权重当原始反馈。
- 关闭的队列样本停用但原始历史不删，不把关闭推断为方向不喜欢。

计划绑定当前输入和查询历史；变化后新轮次必须刷新。同一实际sourcing run只领取一次固定计划。record-search验证既有成功预算query与计划词、来源、时间和实际列表数，new_count由宿主明确核实，未知不默认0。计划和失败不会伪装成已执行；新流程不额外重复调用search-log。

## 迁移与真实接入

迁移18追加八张表；默认物理位置为每位用户私有的.jobagent/jobagent.sqlite3。已发正文、JD、本人原话与消息引用不进入公开Git。升级先备份并停旧任务；新源码/技能改变运行指纹，需新运行或显式迁移。回滚用原私有备份，不能让旧代码读新版库。

数据库是唯一活跃状态权威；queue.jsonl和lexicon-private-vN.md可由宿主导出，不能成为第二套可写状态。next会按需返回JD、当前草稿和已确认证据，输出只保存在私有区。status/list/history不重复输出原始本人话或草稿全文。

本仓库没有真实Muse对话事件连接器、账号或私有任务权限。已更新公开宿主任务模板，真实Muse需拉取此版本，将聊天入口接到enqueue，将每次轮询恢复接到list/next，将搜索轮次接到strategy/claim/record-search，并记录真实任务版本与执行日志。代码接线通过不等于真实宿主任务已经修改。

## 验证

已覆盖入口、身份映射、完整性、实际预算、弱匹配/硬条件、证据ID、独立复核绑定、旧批次摘要、重复与乱序消息、CAS并发、中断恢复、新词幂等、历史样本迁入、同岗合并、两轮计划领取与真实执行归因。最终全套门禁：956 passed（较909基线新增47项），Ruff通过，Mypy检查149个源码文件通过，git diff --check通过。

没有访问真实招聘站点、发送消息、读取真实候选人数据或修改Muse私有任务。
