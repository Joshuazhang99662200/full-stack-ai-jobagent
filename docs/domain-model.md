# 领域模型

## 候选人与证据

`CandidateProfile` 描述候选人是谁。`EvidenceItem` 记录系统凭什么可以做出某项主张。证据保留来源、置信度、确认状态、时序、技能、领域与指标事实。简历是可采信证据之上的一个投影,永远不是候选人事实的权威来源。

自适应面试作用于显式的 `CandidateGap` 记录。回答生成草稿证据;优化器既不能替候选人回答缺口,也不能确认证据。

## 职位与情报

`NormalizedJob` 保全完整 JD 与全部跨源溯源。`JobRequirementProfile` 在不依赖任何连接器的前提下拆解需求。`HardFilterResult` 表示确定性的 `PASS`、`REVIEW`,或带理由的 `REJECT`。`MatchResult` 评估候选人与职位的契合度,并且始终包含解释通道。

离线数据流是:

```text
SourceJobRecord
-> NormalizedJob
-> JobRequirementProfile
-> HardFilterResult
-> RequirementMatchSet
-> MatchResult
-> RankedJob
```

归一化使用稳定的源观测 ID。去重可以指派一个规范组 ID,同时在 `provenance` 中保留每一个源 ID、URL 与采集时间戳。相互冲突的源事实通过 warning 保持可见。

硬过滤先于证据匹配执行。`REJECT` 记录带稳定规则 ID,且绝不进入匹配器。`REVIEW` 记录可以参与匹配以支持决策,但其状态保持为 `REVIEW`。排序对合格评估结果做确定性排列,并把 `application_ready` 保持为 false。

`RequirementMatchSet` 是一份经人工评审的推理产物。它的 job ID、candidate ID、需求覆盖与 Evidence ID 都会被重新校验。只有当前候选人名下、已确认且非弱的证据,才能支撑或部分支撑一条需求。证据缺失会生成缺口或不确定项。

## 简历优化器

`ResumeOptimizationPlan` 把需求映射到证据与被允许的改写操作。`ResumeVariant` 包含选中的证据、优化后的条目、一份 `ClaimLedger`、校验结果、关键词覆盖度与 diff。每一条实质性 `ClaimRecord` 都至少有一个 `EVID_*` ID。

`MatchResult` 与 `ResumeCompatibilityResult` 回答的是两个不同问题:前者衡量这个人是否适合这个岗位,后者衡量某一份简历变体是否呈现了相关且有支撑的证据。

## 投递生命周期

`ApplicationPackage` 是评审产物。`ApprovalRecord` 不可变,把审批绑定到职位、简历、消息与策略摘要。任何一处摘要变化都会让 `ApprovalRecord.matches` 返回 false,投递必须以"审批已过期"失败。

`DeliveryResult` 记录已投递、失败或需人工介入三种状态。`ApplicationAudit` 存放产物 ID、摘要、尝试序号、结果与时间戳,不复制私密的简历或消息正文。

批量执行保持有序且顺序进行。兼容性提案不是审批,审批也不是投递指令。
