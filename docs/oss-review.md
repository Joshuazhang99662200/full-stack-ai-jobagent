# 开源复用评审

核验于 2026-08-21。变更复用方式之前,重新核对上游许可证、notice 文件与锁定的源清单。

| 项目 | 核验 commit | 许可证 | 复用方式 | 预期学习或复用点 | 主要风险 |
|---|---|---|---|---|---|
| [AgentMesh-JobAgent](https://github.com/jiyangnan/AgentMesh-JobAgent) | `291d9dcee29455990ec51935ee15cd911440a297` | Apache-2.0 | Adapter 或子进程 | 平台隔离、连接器工作流、预览/投递/审计分离、可恢复性 | 云端契约与浏览器适配可能变动;必须保留许可证与 notice |
| [open-boss](https://github.com/yinren112/open-boss) | `f1e92275340007ebb460417e5e0d1be14ce1566a` | MIT | Adapter 或参考 | 真实 JD 需求、dry-run、显式审批、隐私、浏览器配置隔离、停止条件 | 平台 DOM 不稳定;复制兼容素材时保留 MIT notice |
| [Auto-JobHunter](https://github.com/jolie-z/Auto-JobHunter) | `4f9dec38978035a87d34cab5b15914dc8688e6f0` | 个人、教育、非商业 | 仅参考 | 高层的 SQLite → 规则 → LLM 评估 → RPA 观察 | 许可证与无限制复用不兼容;不得复制源码、提示词或实现结构 |

## 门禁

引入任何外部素材之前,先记录它属于哪一类:直接复制、作为依赖、子进程包装、经 adapter 集成,还是仅作参考研究。同时记录署名要求、notice 义务、商业限制与 copyleft 传染效果。

领域代码必须独立于每一个上游项目。移除某个上游 adapter,不应改变候选人、职位情报、优化器、审批或审计的任何契约。

机器可读的登记表是[技能上下文的源清单](../skills/job-hunting/references/oss/source-manifest.yaml)。
