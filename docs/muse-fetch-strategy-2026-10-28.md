# Muse fetch 策略修订与第一阶段交付

基准：38afd89ec1ed41ca048fcb23f1c98279f6f9f180。独立工作区 muse-fetch-strategy；不混入上一轮桥接删除实验。本轮不提交、不推送，不访问真实招聘账号。

本次依据用户的 self-evolving-jd-lexicon-thinking-chain.md 做设计评审，并按随后确认落地三项：反馈拆分、薪资规则、读取预算。附件内的“逐步提交/提 PR”等任务清单不是本次额外授权。

## 已覆盖的规则

| 项目 | 行为 |
|---|---|
| 岗位偏好 | SearchSignal 新增 feedback，可独立填写 job_preference |
| 文案反馈 | message_feedback 独立填写；只改文案不影响岗位学习 |
| 薪资默认 | upper_bound，区间能达到本人底线即通过，仅明确上限低于底线才拒绝 |
| 可选严格规则 | 仅本人显式选择 lower_bound 时，要求区间下限也达到底线 |
| 预算 | 每站每轮默认3次查询、20次详情尝试；每天仍受来源<=50详情上限约束 |
| 计量 | 查询、列表观察、详情尝试分开；重复/失败/取消不退额 |
| 并发与恢复 | SQLite 原子预占，同 ID 幂等但不再次允许执行；轮次上限固定；跨当地日需新轮次 |
| 风控 | gate 结果追加后停该站当天新预占 |
| 旧记录 | 仅保留可观察的未精确计量估算，不声称找回历史所有失败/重复读取 |
| Muse 执行 | 先列表去重/预筛再按额度取详情；软词有限调整、探索/稳定/回访与报告写入宿主协议 |

来源的会话总页数与最小翻页间隔继续适用。读取预算与发送每日上限是不同资源，不混算。相同账号应使用同一份私有数据库并保持宿主单实例；本实现没有跨数据库或跨 Muse 账号的全局锁。

## 薪资配置

以下仅为合成示例，金额不是通用默认：

```json
{
  "candidate_id": "CAND_DEMO",
  "minimum_compensation": {"currency": "CNY", "minimum": 18000, "period": "month"},
  "compensation_comparison": "upper_bound",
  "unstated_compensation_passes": false
}
```

15–25k、15–18k、18–25k 在此配置下通过，15–17k 拒绝。只知道足够高的上限或已经达标的下限也可通过；仅知道较低下限而缺少上限时无法确认，保持 REVIEW。未解析/未提供薪资、周期缺失或不可比也保持 REVIEW。不会把13薪、年薪或外币自动换算以满足底线。本人若启用既有 unstated_compensation_passes，会显式接受未知/未解析薪资例外；该例外不会放行明确上限低于底线的区间。

## 新反馈格式

SearchSignal 原有 kind 可继续加载。以下只展示新增字段；其余 event_id、candidate_id、occurred_at、owner_text、job、features 等仍须满足现有契约：

```json
{
  "kind": "feedback",
  "job_preference": "like",
  "message_feedback": "revise",
  "owner_text": "岗位方向合适，招呼请把产品落地写具体一些。"
}
```

只填 message_feedback 不产生岗位偏好，也不覆盖旧的明确选择；job_preference=neutral 明确撤回。拒绝原因仍保留本人原话；只在本人明确点名且有 JD 引文时登记特征反例。L1 原始事件不回写 consumed，不将本人文案确认转换成投递批准。

learn_search 维持 JSON 进出、无 I/O/模型调用；规则标签升级 personal-ai-search-v2，输入顺序改变和重复同文事件仍可确定性重放。升级后版本摘要变化是预期行为，旧策略及信号不删除。

## 预算命令

在宿主私有环境安装同版本包。以下输入路径均在个人私有区，示例不触发网页：

```text
jobagent jobs sourcing-start run.json --database <私有数据库>
jobagent jobs sourcing-reserve attempt.json --database <同一数据库>
jobagent jobs sourcing-result result.json --database <同一数据库>
jobagent jobs sourcing-budget --database <同一数据库>
```

run.json：

```json
{"run_id":"RUN_DEMO_BOSS","candidate_id":"CAND_DEMO","source":"boss","query_limit":3,"detail_limit":20}
```

检索前的 attempt.json：

```json
{"attempt_id":"ATT_QUERY_1","run_id":"RUN_DEMO_BOSS","kind":"query","search_term":"合成产品经理"}
```

查询后的 result.json：

```json
{"attempt_id":"ATT_QUERY_1","outcome":"complete","listing_count":10}
```

取详情前另用新行动 ID：

```json
{"attempt_id":"ATT_DETAIL_1","run_id":"RUN_DEMO_BOSS","kind":"detail","search_term":"合成产品经理","source_job_id":"synthetic-1","url":"https://www.zhipin.com/job_detail/synthetic-1.html"}
```

仅新预占返回 allowed=true 才执行对应只读动作。已有行动 ID 返回 allowed=false / already_reserved，不重复打开页面，先核对检查点。JSON 许可不认证宿主身份，也不授权联系招聘方。

未完成预占保留消耗，不推断网页一定完成。查询完整结果要求 listing_count（可为0）；详情结果不填写列表数。结果不可改写。验证/风控结果填 gate，停止该站。宿主不可借新 run_id 或 action_id 重试门控。来源 URL 和每日上限从同版本清单装配，不能由输入文件提高。

## 修订后的后续词库设计

本轮未实现快照、因子化、Markdown 词库与自动组合查询引擎。下一阶段须遵循以下修订，不能直接照原附件全部编码：

1. JDContentSnapshot 保存原文、原文哈希、完整性与元数据版本；SearchDiscovery 单独记录查询/手动/推荐来源。多查询命中同岗保留多次发现，缺失查询不猜补。
2. 把岗位客观特征与候选人偏好分开。行业/场景/技术/角色是内容；硬要求记录必需/优先及否定；negative 是用户策略，不把电商等行业先验写成负面。
3. 模型新词须有原文准确位置与归一依据，先进入待观察区。引文存在不能单独证明语义、否定和必需性。无词库时允许有据候选，避免永远只能找到已知词。
4. 独立岗位/公司统计、用户反馈与派生权重分开。重复快照不增加独立样本，文案确认不增加 JD 客观词频。组合共现必须保存联合来源，不能从单词边际 count 推断。
5. 词库 MD 管理可编辑的政策/别名/种子和人工调整，版本内容需摘要；统计来自不可变事件，保留人工覆盖来源。结果/消费记录另存，同输入同策略重放不重复升版本。
6. 稳定、探索和冷却回访共存；不以“上轮搜过”永久排除有效查询。不因一个岗位拒绝全部降权，也不因3条同公司负例自动拉黑行业。
7. 搜索结果只能重放当时保存的观测，不能保证平台再次返回相同结果；组合空格语义、完整 JD 与 Muse 页面读取能力仍需逐站只读实测。
8. 不将推荐来源当作可复现搜索；可保留真实观测与入口标记。已移除岗位需保存理由与是否永久排除，不把“暂不处理”永远删除。

## 迁移与验收

数据库由 v13 追加迁移至 v14，保留旧表及批准数据。新版数据库不得交给旧版程序运行。历史寻源记录无法自动恢复成精确尝试；新 protocol 应从新轮次开始，并持久保存原日志。

原 first-launch-boss20、固定周末安排未在该公开基准中找到，不能猜测迁移。运行时应读取使用者实际私有策略，不复用维护者的个人时段、行业或底线。

本次没有修改 outreach、applications 或 candidate 的实现。完整门禁与关键行为测试结果保存于私有 .jobagent/fetch-strategy/；真实 Muse 定时、页面、身份、回读均需另行验收。宿主协议里的软词调整属于执行政策，不能当成新的自动规划引擎已经落地。

## 完成前验证

基线800 passed；首轮836 passed，薪资修正后最终844 passed，累计新增44个用例。Ruff全部通过，Mypy检查129个源码文件无问题，git diff --check通过。预算覆盖重复/失败读取、幂等冲突、轮次冻结、查询与列表数分离、每日共享额度、并发末位、gate停站、当地午夜和旧估算持久保留。

审批与发送的生产代码没有改动；旧审计测试只更新数据库版本断言13→14。源码与技能改动会改变运行指纹，旧 harness 运行须创建新运行或显式迁移，不能删除指纹校验继续。真实 Muse/站点没有执行，836通过不等于已完成网页联调。

完整补丁基于38afd89，并包含新增模块/测试/文档；本次为未提交的源码变更。此补丁独立于上一轮 bridge 裁剪补丁，集成时应审阅二者重叠的文档上下文。原桌面工作区和旧裁剪副本未改动。

薪资修正：本人明确采用区间重叠规则；此前示例中的 lower_bound 已改成 upper_bound。已有私有配置若显式指定 lower_bound，也需同步选择 upper_bound；本次未读取或覆盖个人私有配置。
