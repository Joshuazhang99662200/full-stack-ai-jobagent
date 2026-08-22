# 架构

JobAgent 是一组证据接地、经人工审批的原子求职能力。架构把推理、工作流、契约、平台集成与不可逆决策分层隔离。

## 依赖方向

```text
Typer CLI / MCP / job-hunting Skill
                |
        应用层能力
                |
        领域 schema 与服务
                |
        仓库/提供方端口
                |
SQLite / 推理提供方 / 渲染器 / JobSource 连接器
```

领域模块不 import Typer、SQLite、浏览器自动化、DOM 选择器、Chrome 配置路径、平台 SDK 模型、LangChain 或 LangGraph。平台适配层把外部行为翻译成 `jobagent.capabilities.JobSource` 所暴露的契约。

## 不变式

```text
CandidateProfile != Resume
Evidence is the source of truth
JobSource != Job Intelligence
Job Match != Resume Compatibility
Resume Tailoring != Fact Generation
Preview != Approval
Approval != Send
Platform Connector != Domain Core
Search != Apply
Review != Auto Promote
CAPTCHA != Retry
```

每一个公开能力都有一个类型化输入、一个类型化输出、显式错误,以及零个隐藏的邻接操作。搜索不能投递。预览不能审批。审批不能投递。连接器不能把平台验证转化为绕过行为。

## 安全停止态

连接器把登录、CAPTCHA、验证、风控与平台变更翻译为 `USER_INTERVENTION_REQUIRED`。这些不是可重试的瞬时信号。由用户先在平台上完成操作,之后再显式发起恢复。

## 交付顺序

先有 mock 连接器,再有真实平台连接器。第一条纵向工作流必须能离线跑通:从候选人知识出发,经匹配、优化器校验、评审、审批、mock 投递、兼容性、批量审批,直到审计。

完整阶段图见[基础设计文档](superpowers/specs/2026-08-21-jobagent-foundation-design.md)。
