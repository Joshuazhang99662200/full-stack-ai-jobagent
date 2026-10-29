# 使用指南

[返回首页](../README.md) · [能力目录](../skills/job-hunting/references/capability-catalog.md) · [Personal AI 入口](../hosts/personal-ai/README.md)

以下命令均在仓库根目录执行。CareerHarness 是展示名；GitHub 仓库和 Python 分发包仍为 `full-stack-ai-jobagent`，CLI 为 `jobagent`，安装的 Skill 为 `job-hunting`。请使用同一个已固定版本的代码、策略与运行环境。

先用首页的合成数据体验确认环境，再准备自己的私有资料。下面的 PDF、JSON、数据库与安装路径是示例位置，需要替换成你自己的文件。JSON 输入须满足 `src/jobagent/schemas/` 的契约并经过相应复核。

## 从 GitHub 安装 Skill

需要 Git 与 Python 3.11+。通过构建脚本生成的 zip 包含完整 `job-hunting/`：skill、策略、同版本 runtime、启动脚本与摘要清单。也可从完整 checkout 构建，目标已存在时会拒绝覆盖：

```powershell
git clone https://github.com/Joshuazhang99662200/full-stack-ai-jobagent.git
cd full-stack-ai-jobagent
# Codex 用户级安装
python scripts/build_skill.py --host codex --destination "$env:USERPROFILE/.agents/skills/job-hunting"
# 或 Claude Code 用户级安装
python scripts/build_skill.py --host claude-code --destination "$env:USERPROFILE/.claude/skills/job-hunting"
```

macOS/Linux 的目标分别使用 `~/.agents/skills/job-hunting` 和 `~/.claude/skills/job-hunting`。项目级安装可把目标换成对应 `.agents/skills/` 或 `.claude/skills/`。仅拷贝源码 `skills/job-hunting/` 缺 runtime 与 manifest，不能直接运行；使用完整发布包或上述构建流程。没有发布到 GitHub 的本地改动需先由维护者发布，构建不会自动提交、推送或覆盖宿主设置。

在 Codex 输入 `$job-hunting`，或在 CC 输入 `/job-hunting`，随后说明简历位置、求职方向和个人工作区。技能被调用后先探测依赖；需要时显式创建私有 venv。人工确认仍由用户完成。安装本身不执行搜索、登录、发送或创建计划任务。

```powershell
python <安装目录>/scripts/bootstrap.py --workspace <个人工作区> --check
python <安装目录>/scripts/bootstrap.py --workspace <个人工作区> --setup
python <安装目录>/scripts/bootstrap.py --workspace <个人工作区> -- harness start CAND_001 codex --session-id <随机会话ID>
```

运行状态与产物校验支持中断和 Codex/CC 交接。浏览器、凭证输入、定时与通知由实际宿主提供，缺少则交人；普通 skill 不提供 Muse 的持久云电脑。操作协议见 [Harness](../skills/job-hunting/references/harness.md)，产品与架构差异见 [对比清单](harness-comparison.md)。

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

### 结构化抽取(默认无需凭证)

拉下本仓库执行它的**编码智能体就是推理引擎**。默认的 `--provider agent` 不调用任何模型 API,也不需要厂商凭证:

```powershell
jobagent candidate onboard CAND_001 .\candidate\private\source_resume.pdf
```

正常解析后，命令在交接点输出一个 `AGENT_HANDOFF_REQUIRED` 载荷,并在 `.jobagent/handoff/` 下写一份自足的请求:任务指令、逐页简历正文,以及目标契约的完整 JSON Schema。智能体据此写出 JSON,再执行载荷里的 `resume_command` 完成校验与入库。解析这类确定性结果在暂停前已落库,因此中断安全。完整循环见[智能体推理](../skills/job-hunting/references/agent-reasoning.md)。

`--provider claude` 使用外部 Claude API 执行结构化抽取，需要 `ANTHROPIC_API_KEY` 或 `ant auth login`。

两条路径都受同一套约束:**抽取出的证据一律未确认**——提升为 canonical 证据仍需对每个 `EVID_*` 显式执行 `candidate confirm`,契约本身也会拒收已确认的草稿证据。指令禁止编造未写明的指标与规模,并把简历正文当作数据而非指令。

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

需要先自行安装 [`liepin-cli`](https://github.com/liepin-tech-2026/liepin-cil) 并在可交互终端完成 `liepin-cli setup` 授权(粘贴猎聘官方 `x-user-token`)。寻源侧只读；独立投递连接器因无法传递获批附件和消息，在平台调用前停止并交人。`resume` 写入命令不接入。在线简历已有本地快照、修改提案、审批、放行与回读记账；实际平台填写由宿主执行，须经证据复核、版本摘要人工审批与回读核对，见 [评测操作边界](../skills/job-hunting/references/evals.md)。token 过期、401/403、验证码与风控一律返回 `USER_INTERVENTION_REQUIRED` 交还给人,不自动重试、不更换账号。

搜索与 Job Intelligence 是只读的。它们不暴露平台导航、投递准备、审批或投递操作。

## 外联、对话与巡检

这一段把“发现职位”接到“约到面试”。仓库**不操作招聘网页、不直接发送招聘消息**：浏览器里的操作由宿主在用户自己的浏览器里完成，仓库只回答“这一条能不能发”，并把每一步记成只追加的账。

```text
职位入库并匹配 ─▶ 宿主起草首条招呼 ─▶ outreach draft-batch 逐条校验
      ─▶ outreach ask 把编号清单原样摆给人 ─▶ 人说“发 1-3”─▶ outreach approve
      ─▶ outreach lease / next 发送前复核 ─▶ 宿主在浏览器里发送 ─▶ outreach record 记账
      ─▶ conversations sync-outreach 开对话 ─▶ 对方来信 conversations inbound 分级
      ─▶ draft-reply / approve-reply / reply-gate / record-reply（一条一审）
      ─▶ 对方要简历：optimizer 定向简历 + 独立复核 ─▶ attach-resume ─▶ 逐份审批后发送
```

**首条招呼（`jobagent outreach …`）**
- 起草规则见 [message-generation.md](../skills/job-hunting/references/message-generation.md)「首条招呼」。宿主按完整 JD 与已确认证据生成全文并独立复核；仓库核对数字、禁用词、证据和联系记录，不要求固定开头、话术库挑句或首招字数硬上限。
- 带 `--candidate` 时按匹配档位级联排序：本人挑的 → 强匹配 → 可能匹配 → 未评估。弱匹配、不匹配整条退回。`--filter-context` 里的偏好因子只决定同档内的先后。
- 审批走中继通道：先 `ask` 把编号清单逐字摆给人，人回复后用 `approve --answer "<原话>"` 登记。清单一改，审批即作废。
- 发送有站点租约（一个站同一时间只允许一个会话发）、最小间隔 30 秒、每站每天最多 50 条。遇到失败、登录、验证或风控，该站当天停发，交给人处理。
- 已批准但决定不发的条目，用 `record --result withdrawn` 关闭；没人批过的审批单，用 `withdraw` 作废。

**对话跟进（`jobagent conversations …`）**
- 对话来源分三类，互不混淆：我方外联 `outreach`、招聘方主动来信 `inbound`、用户本人打的招呼 `self`（用 `adopt` 登记）。
- 来信先按排除清单筛：职位或公司命中销售、外包等排除词的直接关闭，不起草回复。
- 来信分 L1/L2/L3/危险/不匹配五级。要简历、约面试、婉拒会自动推进阶段。回复一条一审，发简历必须交出实际上传的文件，文件摘要要和挂上的定向简历一致。

**巡检节奏（`jobagent patrol …`）**
- 宿主的定时器可以随便醒，每次先问 `patrol next`，回答“该查”才动手。
- 默认时段：周日 20:00 到周五 20:00。平时每小时一次；一小时内有新来信时，改为每 15 分钟一次。
- 开工 `record`、完工 `finish`。开工 45 分钟还没完工视为中断，下次醒来立即续查，所以用量耗尽或断网后能安全恢复。
- `snapshot` 把一个站的整份消息列表存进本地库，并返回与上一份的差异：新会话、对方新消息、消失的会话、用户拉起但还没打招呼的会话。
- 快照按来源清单声明同步提取我方消息的已读/送达回执；`receipts` 可回填旧快照，无法唯一匹配的行交人。当前落地部分 P0 埋点及在线简历提案与审批门禁；漏斗计算、诊断、实验和其余飞轮编排仍待实现。

规则全文见 [patrol.md](../skills/job-hunting/references/patrol.md)、[conversation.md](../skills/job-hunting/references/conversation.md)、[browser-sourcing.md](../skills/job-hunting/references/browser-sourcing.md)。设计见 [outreach-design.md](outreach-design.md)、[conversation-design.md](conversation-design.md)。

## 聊天前端桥接：本地 MCP 与会话信箱

想把 Claude Cowork / Claude Desktop 当作人机界面、把编码智能体会话当作执行后端时，用这一层。

```powershell
# 在 Claude Desktop 完全退出时注册（应用退出时会整份回写配置）
python scripts/register_jobagent_mcp.py
# 或手动运行（stdio，标准库实现，无额外依赖）
python -m jobagent.bridge.mcp_server --database .jobagent/jobagent.sqlite3
```

| 工具 | 作用 |
|---|---|
| `status_today` | 三个站今天的发送、已批待发、待审批、来信、详情读取、最新快照 |
| `pending_approvals` | 还没人回答的审批问题，附招呼原文；本身不批准任何东西 |
| `patrol_history` | 最近几轮巡检的开工、完工、是否中断 |
| `new_jobs` | 最近入库的职位与最新匹配档位 |
| `post_to_claude_code` | 唯一的写操作：把用户的审批原话或需求追加进信箱。转达的审批必须对应一张仍在待批的审批单，否则拒收 |
| `receipts` / `notes_from_claude_code` / `peer_sessions` | 读执行会话的逐条回执、留言，以及哪个会话担任哪个角色 |

执行会话一侧用 `jobagent mailbox inbox / ack / notify / register-session / peers`。信箱文件放在 `candidate/private/`，不进 git，只追加。**转达的审批不会自动生效**：执行会话仍要用 `outreach approve` 登记，登记后写回执。MCP 是请求—应答协议，服务端不能主动唤醒空闲会话。目前由巡检或用户触发执行会话读信箱。看板：`python scripts/patrol_dashboard.py`（http://localhost:8765，30 秒刷新）。交接说明见 [cowork-handoff.md](cowork-handoff.md)。

## 简历渲染与 PDF 核对

安装可选渲染依赖后，可以把已校验的变体与页首信息排版为 PDF 或 Word：

```powershell
python -m pip install -e ".[render]"
jobagent harness render .\candidate\variants\verified-variant.json `
  .\candidate\private\header.json --pdf .\candidate\variants\resume.pdf
```

`header.json` 使用 `ResumeHeader` 契约，例如 `{"lines": ["合成候选人", "Python Engineer"]}`。真实联系方式只放在自己的私有文件里。渲染器只排版、不改字；PDF 产出后会运行正文、顺序与页数校验，还需本人逐页视觉检查并批准实际成品。Word 导出成 PDF 后也要重新核对。需要其他模板时，可使用外部渲染技能，但仍须经过相同检查。

## Resume Optimizer 能力发现

在不执行任何被索引入口点的前提下,检视已签入的 Optimizer 能力与策略元数据:

```powershell
jobagent optimizer capabilities
jobagent optimizer capabilities --kind policy
jobagent optimizer capabilities --intent detect_candidate_evidence_gaps
```

这个 Phase 1 命令是只读发现。它校验并报告 L0 索引,同时不加载被选中的策略与技能正文。后续的 Router 阶段才会只加载被选中的资源并补上可执行 adapter。投递审批、投递执行、连接器、浏览器、登录与 CAPTCHA 行为始终在 Resume Optimizer 边界之外。
