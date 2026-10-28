# Muse 寻源知识与已发观察交付记录（2026-10-28）

基于38afd89，分支 codex/muse-snapshots-sent-tracking。先落地预算/薪资与反馈分离，再补原文快照、词库和已发观察。旧本地 bridge 裁剪实验保持独立；本PR没有修改 bridge 或原有 outreach / applications / candidate 的生产实现。

## 六项契约与实现

| 能力 | 类型权威 | 纯逻辑与装配 |
|---|---|---|
| 原文快照/发现 | schemas/jd_snapshot.py：JDSnapshotInput、JDSnapshot、SnapshotDiscovery | jobs/jd_snapshot.py：make_snapshot、capture_from_record；storage/jd_snapshot_repository.py：capture |
| 原文特征 | schemas/lexicon.py：JDFeature、JDFeatureSet | jobs/jd_features.py：extract_features；jobs/jd_factorization.py：factorize |
| 可编辑词库 | schemas/lexicon.py：Lexicon、LexiconTerm、LexiconUpdateResult | jobs/lexicon.py：parse_lexicon、serialize_lexicon；jobs/search_learning.py：rebuild_lexicon |
| 组合查询 | schemas/lexicon.py：CombinationInput、CombinationRequest、CombinationPlan | jobs/query_derivation.py：SearchQueryDeriver.derive_combinations；cli/jd_knowledge.py：combinations |
| 本人反馈 | schemas/search_learning.py：SearchSignal、SearchLearningRequest | jobs/search_learning.py：latest_owner_signals、learn_search、rebuild_lexicon；L1原始文件由宿主私有追加 |
| 已发送观察 | schemas/sent_tracking.py：TrackingStartInput、TrackingEventInput、SentTrackingRecord | jobs/sent_tracking.py：outreach_proof、reply_proof、start_tracking、advance、tracking_report；cli/tracking.py与storage/sent_tracking_repository.py |

## 现有调用点接线

jobs import-observations / add-jd 在归一化前保留原文；有实际时区的完整采集进入私有快照。手工输入明确manual；仅列表标listing；旧无时区记录仍可入原表，但不伪造快照时间。实际查询必填、手工/推荐可为空；同内容不同查询保存发现，同岗正文或元数据改变追加版本。

jobs 的原 search-plan、learn-search 和新 combinations 共存。新计划必须由宿主显式选域与持久快照，保存计划ID；不替宿主执行网页动作。来源预算在动作前预占，失败与重复读取占额；计划不会增加额度。jobs hard-filter 默认比较薪资上限与本人底线，15–25k 对18k接受；未知币种/周期/薪资保持 REVIEW，除非本人显式允许未知。

根CLI新增 tracking 分组，读取已有批准/发送/会话账本。outreach record、next、lease、conversations reply-gate、applications与候选人证据确认实现保持原样。新观察不自动发送、不批量编排，不动态执行技能入口。能力目录和 hosts/personal-ai 三个契约文件同步。

## 相对附件的明确修订

- 继续使用默认每站每轮3查询/20详情尝试、每日最多50详情尝试；不执行8–12查询乘10详情的扩量建议。combinations只排计划，实际预算仍由 sourcing-start/reserve/result 执行。
- “接受文案”不等于“喜欢岗位”。job_preference 与 message_feedback 分离；客观词频来自独立完整JD，不来自批准次数。反馈ID/来源ID与派生摘要代替覆写L1 consumed。没有有据岗位偏好不自动奖励行业。
- 方向拒绝需真实命中查询、本人原话、不同岗位与公司至少3条，仅后移，不删除。工资/地点/文案原因不会降整个查询。
- JD六维保留必需/优先/否定信息，negative是个人政策；模型提案无准确原文偏移或别名依据时整体回退确定性结果。引文只能证明位置，不能证明所有语义判断正确；宿主仍须复核。
- 查询组合保存实际联合来源；人工组合与共现证据分开。无种子保持 needs_seed，不能把维护者金融词表当默认行业。
- 搜索来源要求真实 query_hit；人工/推荐输入允许缺查询并如实标记。连续两轮100%归因是宿主待验收项，当前合成测试不能代替真实平台结果。
- 跟踪 sent_at 来自已有审计的 recorded_at，标明审计时间基准。逐字一致只验证提交回读与批准缓存，不能认证网页账号或倒推旧审计已执行浏览器回读。
- 1/3/7/14天只读节律以第1天到期为默认；漏查至少间隔一天补齐，防止单轮四次读取凑数。既有巡检任务承载检查，没有新增定时守护。
- queue_closed由宿主引用本人原话追加；仓库没有Muse队列事件总线，不能声称自动订阅队列关闭。报告不直接改变词库或候选人证据。
- 沿用可复用 Python 核心与CLI适配层，Muse可使用同一核心；旧bridge未成为依赖，也未在本PR整包删除。无需引入ReAct框架依赖：宿主观察→调用纯能力→校验→追加记录→按需加载下一份上下文。

## 状态、非法转移与并发

完整状态/事件表见 skills/job-hunting/references/sent-tracking.md。建档保留sent与awaiting两条版本；confirmed回复只消费已有INBOUND，旧轮次或未来消息拒绝。awaiting不能直接interview，未读计数不能确认回复，关闭后不能恢复等待，无批准/sent审计或回读不一致不能建档。

有效no_reply最多累计4次且至少14天才归档，漏查不能压缩；明确拒绝、岗位关闭和本人放弃保存终态后追加closed。due只选未暂停的awaiting，closed不再到期。新批准回复回读一致才重置轮次；回读不一致暂停原状态，不重发。数据库BEGIN IMMEDIATE与expected_version保护并发；相同事件重放幂等，冲突ID和旧版本拒绝。历史与发送引用不删除。

## 私有位置、版本、迁移与回滚

运行时默认 .jobagent/jobagent.sqlite3，Muse须传本人私有持久数据库；活跃词库MD、L1反馈、回读输入与来源日志留 .jobagent/ 或 candidate/private/。公开提交只有类型、引擎、策略与明确合成样本。新跟踪历史仅保存正文摘要和来源引用，已有获批全文仍留原私有批次/会话。

迁移14存预算，15存JD/发现/特征/词库版本，16存计划输入输出，17存跟踪roots/events/requests/sends。升级前备份并停旧任务；不能用旧代码读取新版库。运行指纹会变，新运行或显式迁移，不绕过验证。

词库同来源、同政策重算幂等；来源变化才vN递增，保存parent_digest。私有库保留原MD和派生MD，lexicon-show以候选人+内容摘要回读。宿主选择旧版为活跃文件即政策回滚；旧版本和原始记录保留。数据库回滚需恢复升级前私有备份。

## 换域与设计样本

只替换当前域活跃MD中的人工种子、别名和模板，选择该域JD快照/反馈与本人基础查询；不改schema、抽取/因子化引擎、组合算法、预算门禁或审批发送核心。空模板可复制，带金融/设计样例的代码块不自动激活。

合成设计域使用品牌/设计师/Figma，按factorize→rebuild→derive_combinations得到设计查询；无金融硬编码，通用引擎测试覆盖。十组合成JD覆盖否定、必需/优先、别名与准确原文位置。此结果说明同一流程可换域，不代表真实设计岗位搜索质量已获验证。

## 验证与剩余验收

最终全套门禁：909 passed，Ruff通过，Mypy检查142个源码文件无问题，git diff --check通过。跟踪阶段领域/存储/CLI组合26项通过；最终测试还覆盖原有审批、租约、回读、审计及技能打包，不能以局部通过代替全套结果。

本轮没有访问真实Muse或招聘网站、发送招聘消息、读取真实JD/简历、创建宿主定时任务。真实页面完整性、账号回读、单实例恢复和连续两轮归因仍需在Muse按个人设置验收。词库与状态机已可调用，真实宿主效果保持unverified。
