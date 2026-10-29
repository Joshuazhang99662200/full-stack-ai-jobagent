# 流程实现说明

核对日期：2026-10-29。本文用于解释 README 流程图的版本范围，完整[文字底稿](workflow-outline.md)单独保留。本次 README 发布只调整文档和配图，不增加自动化能力，也不改变事实确认与发送门禁。

## 人机协同与确认方式

资料和求职条件由 Agent 整理、追问，本人提供和裁决。事实可以先汇总成有编号的列表或 Markdown，由本人一次确认其中明确的一组；确认须能对应准确内容和证据 ID，不能把“收到了”“继续”推断为批准全部事实。

当前程序接口仍是 `CandidateEvidenceService.confirm(candidate_id, evidence_id)`。宿主依据同一次明确确认，逐项调用这一入口即可，不需要逐项聊天问答，也不能直接写数据库提升证据。若要新增原生的 Markdown 摘要绑定或批量确认命令，还需单独实现与验证；本次没有宣称它已经存在。

## 渠道选择和 JD 补齐

README 将渠道预检前置为接入责任：Agent 先查明可用的官方 MCP / API / CLI、浏览器能力、列表字段和详情能力，再交本人选择。平台有没有对应通道，需要实际验证，不能从站点名称推断。

现有可复用部分包括：

- `src/jobagent/connectors/public_pages.py`：按来源声明读取允许的公开详情页面。
- `src/jobagent/connectors/extraction.py`：JD 两端边界、门控与完整性校验。
- `jobs import-observations`：接收实际宿主取得的观察；网页操作不在领域内实现。
- `jobs ingest-jd` / `jobs add-jd`：接收明确来源的 JD 正文。

统一的“发现通道、让人选择、执行列表读取、在获准通道内自动补详情”的通用接入编排，还不能仅凭这些入口视为已经完成。各站需要在适配层提供经过验证的路径与失败处理，不能把缺口交给运行中的 Agent 临时绕行。遇到登录、验证码、风控、限流或禁止访问时暂停，其他通道也不能用来绕过该状态。

## 对话与简历交换

`src/jobagent/conversation/service.py` 已区分已有对话、来信、本人意向、索取简历和简历已发状态。`INTENT_CONFIRMED` 或 `RESUME_REQUESTED` 且没有对应附件时，会给出定向简历待办。本人明确要求针对具体岗位直接准备申请，也可从独立的简历与投递包链路进入。

AI 可以承担普通回复的写作与复核；发送仍需现有审批。对方索取简历、平台提供“同意交换”按钮，都不是本人的发送批准。附件需属于同一岗位，通过校验与本人查阅，并核对实际文件摘要。面试、联系方式、offer 和危险请求按既有规则交本人处理。

## 运营能力在哪个版本

运营能力已通过 [PR #9](https://github.com/Joshuazhang99662200/full-stack-ai-jobagent/pull/9) 合入 `main`，合并提交为 `f73eb2d`。实现原位于 `codex/pipeline-flywheel`，以下固定快照可用于核对：

```text
710a27da47006113dd12d40ba5e87098db076855
```

该版本已有以下源码与 CLI 入口，源码快照可从[该提交](https://github.com/Joshuazhang99662200/full-stack-ai-jobagent/tree/710a27da47006113dd12d40ba5e87098db076855)核对：

| 部分 | 实现位置 | 入口或行为 |
|---|---|---|
| 流程阶段与实证推进 | `schemas/pipeline.py`、`jobs/pipeline.py` | create、transition、observe、due，保留同一联系轮次 |
| 累计漏斗 | `jobs/pipeline_metrics.py`、`schemas/pipeline_metrics.py` | `pipeline metrics`，计算分子、分母、历史、累计及窗口转化，保存来源证据 |
| 问题段诊断 | `jobs/pipeline_diagnosis.py` | `pipeline diagnose`，核对历史和连续闭合窗口、伴随指标与排除原因；输出诊断建议或继续观察的理由 |
| 具体规则提案与确认 | `storage/pipeline_rules.py`、`schemas/pipeline_rules.py` | `pipeline rule-propose`、`rule-confirm`、`confirmed-rules`，绑定具体规则、范围、诊断和本人原话 |
| 效果复核与回退提案 | `storage/pipeline_rules.py` | `pipeline rule-review`；无效时生成恢复或撤回提案，仍需本人确认 |

该分支的漏斗包含：待批草稿、招呼已发、已读、初步沟通、索取简历、简历已发、待面试、已面试，以及独立的废止原因。指标按平台、方向、场景、技术、招呼版本、简历版本和薪资段切片。它不会把后续联系轮次的转化借给前一轮，也不会把缺少发送证据的条目直接当成已发送。

“已读不回”已有 `read_no_reply_2d` 超时原因及已读到初步沟通的阶段转化。它与旧 `docs/evals-metrics-design.md` 中按成熟观察窗口定义的独立 M2 率，不应混成同一个已实现口径。展示已读不回率时，需要明确分子、分母、截止时间、观察覆盖与排除规则；没有回执不能据此声称未读或未回复。

发布基线 `main` 已包含上述模块。使用尚未更新的本地旧分支时，对应命令仍可能不存在；安装、策略和 runtime 应固定到同一版本，并随该版本核对能力目录，不能把旧工作区与新主分支的代码拼接运行。

规则提案、本人确认、后续读取与效果复核是有程序入口的运营循环；真实网页采集、周期唤醒与现场执行仍依赖宿主。它不等于无人值守投递，也不能改写候选人事实或继承旧的发送审批。
