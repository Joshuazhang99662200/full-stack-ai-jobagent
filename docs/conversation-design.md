# 对话状态：设计稿

状态：已定（2026-10-15），按测试先行实现。上一步见 [outreach-design.md](outreach-design.md)。

## 要解决什么

首条招呼发出去之后，每个职位的对话要能回答这几个问题：对方回了没有？说了什么、属于哪一级？该不该跟进？双方是否有意向？简历做了没有、发了没有？这些答案都要能关联回 `JOB_*`，并且能从记录里重放出来。

## 不做什么

- 不替人回复：每一条回复都要人看过原文并同意，一条一审。
- L3（约面试、交换联系方式、测评链接、offer）和危险信号，智能体只摘要，不起草回复。
- 仓库不读聊天页面：对方消息由宿主在用户浏览器里读到后交给仓库。
- 不把“对方要简历”当成“可以发简历”：发简历仍需定向简历通过校验，并经人确认意向。

## 对话阶段

```text
                    ┌───────────────── 对方主动来信（open）
                    ▼
 outreach 已发 → GREETED ──对方回复──► REPLIED ──人确认意向──► INTENT_CONFIRMED
     │            │                     │  │                       │
     │            │                     │  └─对方要简历─► RESUME_REQUESTED
     │            │                     │                          │
     │            │                     │        定向简历通过校验并经批准发送
     │            │                     │                          ▼
     │            │                     │                     RESUME_SENT
     │            │                     │                          │
     │            │                     └─约面试/联系方式─► INTERVIEW（交人）
     │            │
     │            └─满 2 个工作日未回 → 待跟进；跟进后满 3 天未回 → SILENT
     │
 任一阶段 ──婉拒──► DECLINED（终态）     任一阶段 ──人工结束──► CLOSED（终态）
 SILENT ──对方又回复──► REPLIED
```

阶段只能按上图流转。每次流转都是一条只追加的事件，当前阶段由事件推出来。

## 对方来信的分级

| 级别 | 含义 | 智能体能做什么 |
|---|---|---|
| L1 | 回应招呼、问基本情况、要简历 | 按事实口径起草 ≤80 字回复 |
| L2 | 具体薪资、离职原因、项目细节、异地出差 | 起草，并标出拿不准的点 |
| L3 | 约面试、交换微信 / 手机、测评链接、offer | 只摘要，不起草 |
| 危险 | 要身份证 / 银行卡 / 付费、可疑链接、引导到其他平台 | 只摘要，不起草，不点链接 |
| 不匹配 | 销售、投顾、外包驻场等 | 标已读，不回复 |

分级由宿主判断；仓库按分级执行允许的动作，并强制两条规则：L3、危险、不匹配一律不能起草回复；来信标了“要简历”，阶段自动进入 RESUME_REQUESTED。

## 回复（一条一审）

```text
draft-reply → 校验（阶段、来信分级、长度、黑名单）→ 返回提问（逐字原文 + 对方原话）
approve-reply --request --answer → 人的原话逐字存档；对方又来了新消息，这条审批作废
reply-gate --session → 租约、审批时效、该站当天是否被叫停（与外联共用叫停记录）
宿主发送 → record-reply --result sent | failed | intervention
```

## 意向与简历

- `ask-intent` / `confirm-intent`：确认意向是人的决定。先问后答，答复逐字存档，进入 INTENT_CONFIRMED。
- `attach-resume`：把通过校验的定向简历（`ResumeVariant` 及其 PDF 摘要）挂到对话上；变体未通过校验一律拒绝。
- 发简历附件同样一条一审，经 `reply-gate` 放行后由宿主上传，`record-reply --kind resume` 记账，进入 RESUME_SENT。

## 到期提醒（`due`）

按工作日计算（周一到周五）：

- GREETED 满 2 个工作日没有来信 → 待跟进；
- 跟进后满 3 天没有来信 → 建议转 SILENT；
- INTENT_CONFIRMED 或 RESUME_REQUESTED 但还没挂简历 → 待做定向简历；
- 有未处理的 L3 或危险来信 → 待人处理。

## 存储

迁移 `0005_conversations.sql`：对话（当前阶段是事件的投影）、对话事件（只追加）、提问。消息原文只存在本地私有数据库，不进日志与仓库文件。

## 命令

`jobagent conversations sync-outreach | open | inbound | transition | ask-intent | confirm-intent | draft-reply | approve-reply | reply-gate | record-reply | attach-resume | due | show | list`
