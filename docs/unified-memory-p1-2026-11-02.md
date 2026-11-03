# 统一记忆第一期：来源、快照和任务上下文

本页说明已在本地实现的第一期调用边界。总体路线见 [统一记忆闭环方案](unified-memory-muse-plan-2026-11-01.md)。后续的实际模型消费、反馈关联和运营效果仍需分别实现、验收。Muse 必须先取得包含这些入口的同版本代码；只收到文档或读取未包含本地改动的 GitHub SHA，不能执行这些新命令。

受控模型实验已执行，结论与保留失败见 [原型验证说明](unified-memory-validation-2026-11-03.md)。实验可运行不代表统一生产消费或 Muse 接线已完成。

## 这期解决什么

宿主在任务前能查清来源是否存在、是否可读取、属于哪位用户，再保存一份不可变的来源快照。搜索或写招呼语时，按任务和岗位选取受支持的内容；来源变了，就先更新快照。整个过程不调用模型、不重算学习结果、不改业务状态。

快照只保存来源身份、摘要和诊断。规则正文仍从原有私有来源读取，不维护第二份业务当前态。快照存储与业务数据库分开，不对 Muse 的旧库自动迁移。

这期提供三个入口：`jobagent memory status`、`jobagent memory compile`、`jobagent memory context`。具体参数以同版本 `--help` 为准。下文的路径、用户编号和文件名均为合成示例。

## 来源的含义

| 来源类型 | 这期怎么用 | 不能据此声称什么 |
|---|---|---|
| `preference_memory` | 读取现有私有偏好文件，检查完整性、候选人和版本；只选择范围能确定的软建议 | 文件摘要有效，不代表本人批准了全部建议；总结不能改候选人事实或硬条件 |
| `confirmed_rules` | 通过既有规则仓储、只读事务读取本人确认规则；不支持的范围排除并保留诊断 | 读取确认规则，不代表模型已经收到或遵循；不授予发送权 |
| `legacy_inventory` | 对旧文件做来源盘点与版本绑定，保持宿主报告等级 | 不把任意 JSON 中的 accepted、sent 或 consumed 当成已批准、已发送或已学习 |
| 其他来源 | 明确报告未接入 | 不静默解释成空结果，也不临时猜字段含义 |

角色范围的自然语言条件，需要语义消费者才能判断；第一期不能凭字符串猜它是否适用。单岗偏好只给对应岗位。运营诊断规则也不能脱离其原来范围当全局文案规则。

来源正文一直作为数据读取。JD、反馈文件或规则正文里的工具操作指示不能扩大权限、触发命令或代替用户批准。

## Muse 如何配置

在用户自己的持久工作区内运行，配置、来源和快照文件放在 `candidate/private/` 或 `.jobagent/` 下。`private_root` 指向其中的私有目录，全部来源与快照存储须落在该目录内。来源相对路径以 `private_root` 为起点；命令参数和 `private_root` 的相对路径以当前工作区为起点。目录外路径、穿越路径和逃逸的符号链接不能作为来源。

```json
{
  "candidate_id": "CAND_DEMO",
  "private_root": "candidate/private/memory-demo",
  "sources": [
    {
      "source_id": "writing-preferences",
      "kind": "preference_memory",
      "path": "preferences.md",
      "candidate_id": "CAND_DEMO"
    },
    {
      "source_id": "existing-rule-ledger",
      "kind": "confirmed_rules",
      "path": "jobagent.sqlite3",
      "candidate_id": "CAND_DEMO"
    },
    {
      "source_id": "legacy-queue",
      "kind": "legacy_inventory",
      "path": "queue.jsonl",
      "candidate_id": "CAND_DEMO"
    }
  ]
}
```

这些设置只说明从哪里读取，不证明原文件里的本人身份、确认原话或平台结果。Muse 先核对实际来源再登记，不能为了通过检查给旧文件补造用户编号或确认记录。

同一个任务的来源必须属于同一候选人。不能把别人的偏好拼进来，也不能把一个数据库的当前态与另一份历史快照悄悄混用。真实配置、来源、正文与数据库都留在私有区，不放进公共仓库。

## 调用顺序

先检查当前固定代码版本下的帮助，然后用显式配置和独立快照文件操作。Windows 可使用同样参数配合本机私有绝对路径。

```sh
jobagent memory status --config candidate/private/memory-demo/memory-config.json --store candidate/private/memory-demo/memory-snapshots.sqlite3
jobagent memory compile --config candidate/private/memory-demo/memory-config.json --store candidate/private/memory-demo/memory-snapshots.sqlite3
jobagent memory context --config candidate/private/memory-demo/memory-config.json --store candidate/private/memory-demo/memory-snapshots.sqlite3 --snapshot SNAPSHOT_FROM_COMPILE --task greeting --job JOB_DEMO
```

1. **`status`**：盘点当前来源。它不创建快照库，不建来源目录，不修复来源，不迁移数据库。缺表、缺文件、读失败与完整空来源分别诊断。
2. **`compile`**：校验来源并写入独立的派生快照库。相同来源配置及内容得到相同快照身份；重复调用不增加反馈样本，不把编译时间当业务时间。
3. **`context`**：为 `search` 或 `greeting` 返回范围明确的内容与诊断。它从原来源重读，并检查与快照的摘要是否一致。发生变化、来源消失或无法验证时，不继续返回旧规则冒充当前内容。

快照 ID 应直接取自 `compile` 的结构化结果，不按显示序号或文件日期猜测。`context` 回显 `candidate_id`、`task`、`job_id`，并以 `context_digest` 绑定本次返回内容；Muse 要核对这些值与当前任务相符。上下文摘要只表示这份内容的身份，不证明模型消费、本人批准或业务效果。调用后同时检查 `usable`、`status` 和诊断；进程正常退出不能代替业务可用性检查。不要忽略部分来源失败后宣称“全部历史已读”。

冲突检查当前覆盖同编号、不同正文的规则；不同编号之间的自然语言语义冲突没有自动裁决能力。软建议不能覆盖硬条件和本人确认规则，准确产物仍须经过原有复核与审批。

`reply` 和 `resume` 当前返回未接入。旧快照元数据通过 `MemoryRepository.get` 读取用于追溯；这期没有保存历史正文副本，也没有跳过新鲜度检查来重放旧正文的 CLI 开关。

进程内集成复用 `MemoryService`、`PrivateSourceReader` 和 `MemoryRepository`，不能让宿主另写一套选择逻辑。配置及返回结构的 JSON Schema 从 `src/jobagent/schemas/memory.py` 中对应模型的 `model_json_schema()` 取得。CLI 新增不代表 Muse 的 MCP 工具已经注册，包装成工具仍需独立接线。

## 放进 Muse 哪一步

在原任务流程中加两个位置即可，不新建一条并行投递流程：

```text
恢复任务、复用已确认配置
  → status 核对来源
  → 来源有更新时 compile
  → 搜索或起草前 context
  → Muse 按返回范围组织本次输入
  → 原有的搜索预算、草稿复核、逐项审批和结果回读
```

Muse 可以自由组织自然语言和建议，但不能把诊断中的缺失改成成功，也不能自行扩展规则的适用范围。原始反馈、规则确认和结果继续由已有业务服务保存；不要直接写 SQL 去“补齐”确认链。

面板的普通用户只需看到与当前工作相关的结果，例如“已读取你的写作偏好”“这份偏好有更新，需要重新读取”。字段名、摘要、路径及诊断详情放在维护者的原始记录里。不要向用户承诺“越写越准”已经得到数据验证。

## 这期与完整闭环之间还差什么

| 事件 | 第一期能证明吗 | 后续需要的证据 |
|---|---|---|
| 来源存在、版本被固定 | 在本地受支持适配器的验证范围内可以 | Muse 真实路径和同版本代码的运行回执 |
| 某条建议被选入上下文 | 可以 | 返回的上下文与来源引用 |
| 建议实际进入模型请求 | 不可以 | 适配器捕获的实际输入、上下文摘要与产物绑定 |
| 模型遵循了建议 | 不可以 | 对准确产物的独立复核 |
| 反馈进入下一次任务 | 不可以 | 原始反馈、规则版本、下一次输入与输出的连续关联 |
| 回复率或投递率改善 | 不可以 | 统一分母、窗口、来源与规则版本的真实运营记录 |

`memory applied`、`memory link-result`、`memory analyze` 尚未实现。搜索学习、词库和运营模块继续沿用已有入口，不能把三个查询入口当成这些消费者已经自动接通。

## Muse 还要补什么

已有材料不用重写。接线时只补以下最小回执；找不回的历史如实标缺失：

1. 一次真实私有来源读取：固定代码版本、只读查询回执、文件摘要及读取范围，能对上面板中的一条记录。
2. 一条已有的批准与交付链：原始决定、准确正文和附件、平台结果及正向回读；没有完整记录时不能倒填过去的批准。
3. 一次新任务的真实模型消费：原始反馈或规则版本、实际请求和输出摘要。可先做明确标为合成的演练，不能冒充历史或生产效果。
4. 一次完成与恢复演练：重复请求、保存失败、中断恢复后的实际结果与去重依据。无须为验收新发招聘消息。

资料到件、只读适配器可用、模型真实消费、业务批准有效和运营效果验证，分别验收。第一期通过不代替后四项。
