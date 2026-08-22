# 人工审批的 JobAgent

一个证据接地、经人工审批的 AI 求职智能体。

JobAgent 是一组原子、可审计的能力,覆盖候选人知识、职位情报、证据接地的简历优化、投递包评审与经审批的投递。它被设计为可从 Python、CLI、MCP 与编码智能体技能中调用。

## 它不是什么

JobAgent 不是自动批量投递机器人。搜索、匹配、简历生成、预览、审批与投递始终是彼此独立的操作。平台验证与风控状态会中止工作流,交由人处理。

## 当前阶段

架构契约、Candidate Core、离线 Job Intelligence,以及 Resume Optimizer Phase 1 能力索引已经实现。

Candidate Core 可以解析 PDF 简历并保留页码溯源、把候选人私密知识持久化到本地 SQLite、导入结构化推理草稿、检测缺口、提出一个自适应面试问题、记录草稿证据、显式确认证据,并报告就绪度。

Job Intelligence 搜索内置的合成数据源,归一化并去重职位,保全每一条源观测,校验经评审的需求与证据映射,执行确定性硬过滤,计算可解释匹配结果,对合格职位排序,并把产物存入 SQLite。

真实平台连接器、可执行的 Optimizer adapter 与运行时提示词,以及投递门禁,属于后续独立阶段。**消息生成、评审包、审批、投递、批量与审计目前只有 Pydantic 契约,没有可执行代码。** 各能力的确切状态见[能力目录](skills/job-hunting/references/capability-catalog.md)。

## Candidate Core 快速开始

安装本包与开发工具:

```powershell
python -m pip install -e ".[dev]"
```

开发期间请显式指定本地数据库:

```powershell
jobagent candidate ingest CAND_001 .\candidate\private\source_resume.pdf `
  --database .\.jobagent\jobagent.sqlite3

jobagent candidate import-draft .\candidate\private\candidate-draft.json `
  --database .\.jobagent\jobagent.sqlite3

jobagent candidate question CAND_001 --target-role "Python Engineer" `
  --database .\.jobagent\jobagent.sqlite3

jobagent candidate status CAND_001 --target-role "Python Engineer" `
  --database .\.jobagent\jobagent.sqlite3
```

`ingest` 只做本地 PDF 文本与溯源抽取。`import-draft` 接收由经评审的提供方或测试 fixture 产出的类型化 `CandidateDraft` JSON。模型产出与面试产出的证据保持未确认状态,直到针对某个具体的 `EVID_*` ID 调用 `jobagent candidate confirm`。所有命令默认输出 JSON。

候选人源文件、SQLite 数据库与结构化草稿可能包含个人数据;请把它们放在被 gitignore 的本地路径下,例如 `candidate/private/` 与 `.jobagent/`。

## Job Intelligence 快速开始

内置 fixture 是合成数据,支持完全本地的发现流程:

```powershell
jobagent jobs search python
jobagent jobs fetch alpha-001
jobagent jobs normalize alpha-001
jobagent jobs dedupe alpha-001 beta-991
```

依赖推理的命令消费经人工评审的类型化 JSON。这让提供方输出停留在一个显式的校验边界上:

```powershell
jobagent jobs requirements alpha-001 .\reviewed\requirements.json

jobagent jobs filter alpha-001 .\reviewed\requirements.json `
  .\candidate\private\filter-context.json

jobagent jobs match alpha-001 .\reviewed\requirements.json `
  .\reviewed\mappings.json CAND_001 --database .\.jobagent\jobagent.sqlite3
```

使用 `jobs pipeline` 时,把已评审文件按 `JOB_ID.requirements.json` 与 `JOB_ID.matches.json` 放在同一个目录下。被拒绝的职位不需要 mappings 文件,因为确定性过滤会在匹配之前把它拦下。pipeline 输出的 `application_ready` 恒为 `false`;`REVIEW` 保持可见,交由人来裁决。

搜索与 Job Intelligence 是只读的。它们不暴露平台导航、投递准备、审批或投递操作。

## Resume Optimizer 能力发现

在不执行任何被索引入口点的前提下,检视已签入的 Optimizer 能力与策略元数据:

```powershell
jobagent optimizer capabilities
jobagent optimizer capabilities --kind policy
jobagent optimizer capabilities --intent detect_candidate_evidence_gaps
```

这个 Phase 1 命令是只读发现。它校验并报告 L0 索引,同时不加载被选中的策略与技能正文。后续的 Router 阶段才会只加载被选中的资源并补上可执行 adapter。投递审批、投递执行、连接器、浏览器、登录与 CAPTCHA 行为始终在 Resume Optimizer 边界之外。

## 文档

- [架构设计](docs/superpowers/specs/2026-08-21-jobagent-foundation-design.md)
- [Job Intelligence 设计](docs/superpowers/specs/2026-08-21-job-intelligence-design.md)
- [Optimizer 设计](docs/superpowers/specs/2026-08-22-resume-optimizer-router-skill-design.md)
- [架构总览](docs/architecture.md) · [领域模型](docs/domain-model.md) · [开源复用评审](docs/oss-review.md)

面向编码智能体的上下文在 [`skills/job-hunting/`](skills/job-hunting/SKILL.md);`docs/superpowers/` 下的 specs 与 plans 是历史评审记录,保持英文原样。
