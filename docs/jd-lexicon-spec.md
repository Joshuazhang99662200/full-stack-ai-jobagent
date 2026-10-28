# 私有 JD 词库格式与版本

本仓库分发方法、类型与通用引擎；实际词库、JD、反馈和查询计划保存在每位使用者自己的私有区。空模板见 skills/job-hunting/references/lexicon-template.md，其中金融与设计样例都为虚构格式示例，代码不会把附录代码块当成活跃词项。

## 格式

YAML 头必需 lexicon_version（v1起）、domain、updated_at、based_on_snapshots、based_on_feedback_events。缺版本或字段拒绝。派生头可包含 derivation_digest、parent_digest、feedback_event_ids 与 snapshot_ids，保留来源、版本与重放依据。

正文固定六节：domain、scenario、tech、role、hard、negative，标题最后一段使用对应英文维度。条目格式：

```markdown
## 技术词 tech
- RAG | count: 0 | last_seen: null | source: 人工 | aliases: ["检索增强"] | seed: true | author: synthetic-owner | round_id: INIT | weight: 1.0
```

每条必须显式写 count、last_seen、source。source只接受 JD快照 / 人工反馈 / 人工；人工条目需 author、round_id，只有人工种子可 seed=true。可选 aliases 为JSON数组，weight为本人手动政策权重，范围0–10，0表示本人禁用该条目的正向查询。词项与备注不可带竖线或换行，避免分隔歧义。YAML使用安全解析，不执行代码。

count统计选中岗位的最新完整快照，不因重复抓取、同岗多查询或批准增加。independent_companies与maturity来自选中的来源快照；preference_weight只从明确本人岗位偏好重算，不从回复、无回复、点击、词频或文案修改推断。自动候选至少两个独立公司重复出现才进入组合探索，人工种子可冷启动。修改自动词条的count不能替代原文和来源；计划阶段重新按持久化特征核算。

组合模板为2–4个概念组件，只允许domain/scenario/tech/role。英文角色名中的空格不额外拆词。默认支持域×角色、域×场景×角色、场景×技术×角色、域×技术×角色。hard与negative不直接拼正向查询，也不自动变成全行业过滤。模板不能带属性访问、代码或其他占位符。

## 执行

```text
jobagent jobs snapshot capture.json --database <私有数据库>
jobagent jobs factorize <snapshot_id> lexicon.md --database <同一数据库>
jobagent jobs lexicon-update lexicon.md signals.json --snapshot-id <snapshot_id> --database <同一数据库>
jobagent jobs lexicon-show <candidate_id> <version_digest> --database <同一数据库>
jobagent jobs combinations lexicon.md plan-input.json --snapshot-id <snapshot_id> --database <同一数据库>
jobagent jobs combinations-report <plan_id> --database <同一数据库>
```

factorize不调用模型。可传--model-output接收宿主按JDFeatureSet契约写出的JSON；缺失/格式/证据/别名/否定信息不合法会返回fallback与稳定错误码，不输出错误原文。默认纯规则，完整性状态来自宿主观察，程序不能仅凭哈希证明网页已读完整。

signals.json沿用SearchLearningRequest与岗位/文案分离反馈。query_term必须对应job.search_term，方向拒绝还须明确本人原话与rejection_reason=direction。三条独立公司、不同岗位的明确方向拒绝只后移对应查询，不删除；薪资/地点/文案原因不会降权该查询。后移是可解释启发式，不是统计显著结论。

plan-input.json只接受candidate_id、source、query_limit、cooldown_hours、baseline_queries与可选learning。时间、历史、特征由CLI从程序时钟和同一私有数据库装配。计划不会记成已执行搜索；实际搜索仍走sourcing-reserve/result与search-log。默认最多3查询（上限6），不超过来源页数与预算。每维最多20个合格词，全部组合最多256，超限明确拒绝，要求本人缩小范围，不静默裁掉后声称完整。

近期查询默认冷却24小时，仍留在deferred_queries，之后回访。没有合格组合时明确needs_seed并返回本人基础词，不臆造行业。每个计划保留规则、词库、输入、来源、权重理由与输出，可通过combinations-report反查；跨站不同搜索语义仍需宿主实测。

## 版本与回滚

重算是绝对计算，不回写L1的consumed。相同输入与政策产生相同摘要；重复使用最新词库重跑不增加版本。新快照或有效岗位反馈改变来源摘要时递增vN，保存parent_digest与源ID。文案事件只记忽略回执，不改变词库版本。

lexicon-update保存原版和新版到私有数据库，输出新版JSON，不自动覆盖本人MD。宿主核对后用序列化结果替换自己的活跃文件，并回读确认。lexicon-show按候选人+内容摘要读取旧MD，回滚时由宿主明确选择旧版本作为活跃文件；历史不删除。同一个v2标签可能来自分叉政策，准确身份以内容摘要为准。

换域：复制空模板 → 填域与有来源的人工种子 → 为该域选择JD快照 → factorize → lexicon-update → 保存并回读活跃MD → combinations。不同域实例分开文件，不能把维护者词表当成所有用户默认。使用品牌/设计师/Figma的合成样本已可运行同一引擎；没有金融领域分支。

任何搜索学习与阅读许可均不授予招呼/回复/简历发送权。真实资料和生成MD仅留私有区，不提交公共仓库。
