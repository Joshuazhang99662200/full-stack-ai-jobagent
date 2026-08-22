# 职位情报

寻源、归一化、去重、JD 拆解、硬过滤、人岗匹配或排序时,使用本上下文。

## 必须遵守的阶段顺序

1. 通过只读的 `JobDiscoverySource` 搜索。
2. 归一化每一条 `SourceJobRecord`,不丢弃完整 JD。
3. 对等价的观测记录去重,并保留全部溯源。
4. 抽取原子的 `JobRequirement` 条目,并带上确切的 JD 源文片段。
5. 执行确定性硬过滤。
6. 对 `REJECT` 的职位跳过证据匹配。
7. 把剩余的每一条需求映射到候选人证据。
8. 确定性地聚合分数,并对合格的评估结果排序。

`HardFilterResult` 必须与语义匹配分开。返回 `PASS`、`REVIEW` 或 `REJECT`;每一次 reject 都要有稳定的规则 ID 与解释。`REVIEW` 必须一路保留到排序阶段,且 Phase 3 中每个 `RankedJob.application_ready` 的值都为 false。

## 证据边界

supported 与 partial 映射只能引用满足以下全部条件的 Evidence:

- 属于当前候选人;
- 已被用户显式确认;
- 置信度为 `explicit` 或 `inferred`;
- 经结构化校验后与需求语义重叠。

弱证据或未确认证据可以用来说明不确定性,但不能支撑主张。未知的 Evidence ID、需求覆盖不完整、外来的 Candidate ID,以及 JD 中不存在的源文片段,都会使这份经评审的推理产物失效。

匹配结果需报告各维度分数、优势项、部分匹配项、硬缺口、不确定项与 Evidence ID。只给一个百分比是非法的。人岗匹配度与简历兼容性是两份独立契约。职位情报产物是优化器的输入上下文;它们既不为简历主张背书,也不授权投递。

## 本地命令路由

确定性的源数据处理使用 `jobagent jobs search|fetch|normalize|dedupe`。在未配置运行时提供方的情况下,把经评审的 `JobRequirementProfile` 与 `RequirementMatchSet` JSON 传给 `requirements`、`filter` 与 `match`。`pipeline` 命令按 `JOB_ID.requirements.json` 与 `JOB_ID.matches.json` 解析已评审文件,并把结果持久化到本地 SQLite。
