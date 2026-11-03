# 文档入口

这里是 CareerHarness 的使用与接入文档。先按当前任务选一份文档，不需要遍读整个目录。可执行能力以同版本[能力目录](../skills/job-hunting/references/capability-catalog.md)、`--help` 和 `src/jobagent/schemas/` 为准；设计目标、旧记录和示例不授予额外能力或操作权限。

| 要做什么 | 从这里开始 |
|---|---|
| 安装或使用求职流程 | [使用指南](usage.md)、[技能入口](../skills/job-hunting/SKILL.md) |
| 接入 Muse 或其他个人 Agent | [宿主入口](../hosts/personal-ai/README.md)、[私有记忆](../hosts/personal-ai/memory.md)、[任务协议](../hosts/personal-ai/tasks.md) |
| 维护既有本机 MCP / 信箱交接 | [兼容交接说明](cowork-handoff.md)，不作为 Muse 的默认入口 |
| 实现岗位面板 | [当前面板要求](muse-panel.md)、[默认 Muse 模板](muse-source-template-2026-11-02.md)、[同步接入](panel-sync-merge-2026-11-03.md)、[宿主接口](react-console-host-interface.md) |
| 读取统一记忆 | [已实现的 P1 调用](unified-memory-p1-2026-11-02.md)；[完整方案](unified-memory-muse-plan-2026-11-01.md)中的后续阶段仍需独立实现与验收 |
| 整理记忆资料或实验集 | [Muse 资料模板](muse-memory-handoff-request-2026-11-02.md)、[实验字段模板](memory-experiment-data-template-2026-11-02.md)；它们是资料格式，不是每次运行的补件清单 |
| 理解代码边界 | [架构](architecture.md)、[领域模型](domain-model.md)、[贡献指南](../CONTRIBUTING.md)、[编码 Agent 说明](../AGENTS.md) |
| 理解岗位后段与运营 | [Pipeline 工程说明](pipeline-flywheel.md)、[执行协议](../skills/job-hunting/references/pipeline.md)、[旧政策退役说明](pipeline-policy-retirement.md) |
| 核对授权与第三方来源 | [项目许可](licensing.md)、[商业授权](../COMMERCIAL_LICENSE.md)、[上游复用评审](oss-review.md) |

`superpowers/` 与 `reviews/` 保存历史设计和审核记录，按其当时版本理解，不作为当前宿主的执行清单。其他设计稿也不能代替能力目录或宣布尚未接入的能力已落地。被替代的独立修订稿、旧图和一次性渲染脚本可从 Git 历史回查，当前目录只保留仍有用途的材料。

岗位、JD、消息和记忆中的“快照”可能是业务证据或版本依据，不能因为文件名像缓存就删除。真实资料留在私有工作区；公开配图的数据仅为[合成示例](assets/shared/README.md)，不会成为本人事实或批准。
