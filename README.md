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

### 结构化抽取(需要 Claude 凭证)

`ClaudeReasoningProvider` 实现 `ReasoningProvider` 端口,是仓库里唯一感知厂商的推理模块。它把 PDF 页面文本转成结构化 `CandidateDraft`:

```powershell
jobagent candidate onboard CAND_001 .\candidate\private\source_resume.pdf
```

需要 `ANTHROPIC_API_KEY`,或用 `ant auth login` 建立配置档。**抽取出的证据一律未确认**——提升为 canonical 证据仍需对每个 `EVID_*` 显式执行 `candidate confirm`。提示词禁止模型自行确认证据、禁止编造未写明的指标与规模,并把简历正文当作数据而非指令。

没有凭证时返回 `USER_INTERVENTION_REQUIRED`;模型拒答、输出被截断或不满足契约时分别返回对应的类型化错误,绝不返回半成品草稿。

### 补齐 JD 正文

猎聘把 JD 放在公开详情页的服务端渲染 HTML 里,因此不需要登录、浏览器或 Cookie:

```powershell
jobagent jobs fetch-jd .\reviewed\listing.json
```

抽取是**有边界的**:JD 块在第一个后续小节处截断,因为原始页面还带着公司简介、防诈提示与推荐职位位。页面被登录墙拦截、缺少职位介绍段落或抽取结果过短时,一律报错而不是保存半截 JD——被污染的 JD 流进需求抽取,比没有 JD 危害大得多。

单条、由人触发,不做批量爬取。

### 用简历关键字检索

`suggest-queries` 从候选人库**已确认**的证据里确定性地推导检索词并按信号强弱排序,每一条都带回支撑它的 Evidence ID:

```powershell
jobagent jobs suggest-queries CAND_001 --location 上海
```

它只做词项选择,不生成事实:所有词都已存在于 profile 中。未确认的证据不能支撑任何词项,会计入 `skipped_unconfirmed_evidence_count`。把输出的 `term` 接给 `jobs search` 即可。

### 真实来源:猎聘 listing(只读)

猎聘的搜索接口**不返回 JD 正文**,只返回结果页字段。因此它无法产出 `SourceJobRecord`,而是产出一个独立的 `JobListing` 契约:职位名、公司、地点、薪资、学历、年限、行业、公司标签、规模、融资阶段、详情页 URL。

```powershell
jobagent jobs listings "AI Agent 产品负责人" --location 上海
```

listing 用于**发现与确定性硬过滤**(薪资、年限、学历、行业都在),但**不能替代 JD**。定向改写仍需要 JD 正文,由人补齐后走 `jobs search` 那条完整链路。`jobs search --source liepin` 会被显式拒绝并指向本命令,而不是合成一段假 JD。

需要先自行安装 [`liepin-cli`](https://github.com/liepin-tech-2026/liepin-cil) 并在可交互终端完成 `liepin-cli setup` 授权(粘贴猎聘官方 `x-user-token`)。该 CLI 的 `job apply` 与 `resume` 写入命令有意**不接入**——投递属于独立边界,在线简历保持只读。token 过期、401/403、验证码与风控一律返回 `USER_INTERVENTION_REQUIRED` 交还给人,不自动重试、不更换账号。

搜索与 Job Intelligence 是只读的。它们不暴露平台导航、投递准备、审批或投递操作。

## Resume Optimizer 能力发现

在不执行任何被索引入口点的前提下,检视已签入的 Optimizer 能力与策略元数据:

```powershell
jobagent optimizer capabilities
jobagent optimizer capabilities --kind policy
jobagent optimizer capabilities --intent detect_candidate_evidence_gaps
```

这个 Phase 1 命令是只读发现。它校验并报告 L0 索引,同时不加载被选中的策略与技能正文。后续的 Router 阶段才会只加载被选中的资源并补上可执行 adapter。投递审批、投递执行、连接器、浏览器、登录与 CAPTCHA 行为始终在 Resume Optimizer 边界之外。

## 参与与安全

- [贡献指南](CONTRIBUTING.md) —— 环境、质量门禁、架构不变式、新增能力的步骤
- [面向编码智能体的说明](AGENTS.md) —— 在本仓库里工作的智能体先读这份
- [安全策略](SECURITY.md) —— 漏洞报告通道与威胁模型边界
- [隐私说明](PRIVACY.md) —— 简历数据去了哪里、推理提供方看到什么、如何删除

## 文档

- [架构设计](docs/superpowers/specs/2026-08-21-jobagent-foundation-design.md)
- [Job Intelligence 设计](docs/superpowers/specs/2026-08-21-job-intelligence-design.md)
- [Optimizer 设计](docs/superpowers/specs/2026-08-22-resume-optimizer-router-skill-design.md)
- [架构总览](docs/architecture.md) · [领域模型](docs/domain-model.md) · [开源复用评审](docs/oss-review.md)

面向编码智能体的上下文在 [`skills/job-hunting/`](skills/job-hunting/SKILL.md);`docs/superpowers/` 下的 specs 与 plans 是历史评审记录,保持英文原样。
