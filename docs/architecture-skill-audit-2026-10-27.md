# 技能与代码结构审查

日期：2026-10-27。对象：当前本地工作区，包含已有未提交改动；结论不等同于 GitHub 已发布版本。此次审查不改业务代码、不更新已安装技能、不执行真实模型调用或求职操作。

## 结论

建议做局部、分阶段重构，保留现有领域核心。最优先的问题是安装入口漂移、策略重复维护和任务上下文过量；其次是 CLI / bridge 中的编排耦合。现有证据、独立复核、审批、租约和审计机制有明确职责，尚无理由整体换成通用 Agent 框架。

仓库本身只有 3 个 `SKILL.md`，分别为主入口、简历优化路由、固定 Word 母版定向改写；`job-hunting/references` 下有 47 篇 Markdown。参考资料的数量不等于每轮加载量，也不能用 Python 是否 import 某篇文档来判断它是否无用。

当前源码为 151 个 Python 文件、21,583 行。对 candidate、jobs、optimizer、outreach、conversation、applications 的 43 个模块做静态导入检查，未发现 Typer、SQLite、浏览器 SDK 或对 CLI / storage / bridge 的反向依赖。这个分层基础应继续保留。

## 验证结果与限制

- 原始 `python -m pytest -q` 遇到沙箱默认临时目录不可写；首项诊断为 pytest fixture 创建目录失败，尚未进入业务断言。
- 改用工作区 `.jobagent/` 下的新临时目录，全套结果为 **1032 passed、1 failed**，耗时 201.68 秒。
- 失败项：`tests/bridge/test_preference_signals.py::test_raw_context_keeps_revision_requested_and_exact_original_revision_pair`。第 191 行预期 `revision_requested`，实际 `rejected`。
- `python -m ruff check .` 通过。
- `python -m mypy src/jobagent` 通过，检查 151 个源码文件。
- `git diff --check` 通过，仅有现有文件 LF/CRLF 提示。

失败已定位为测试时钟漂移：`tests/bridge/test_greeting_context.py:22,63` 用固定的 2026-10-26 00:00 UTC 创建审批问题；`feishu_paged_approval.py:50` 使卡片在 24 小时后到期。失败测试调用处理器时没有传入 `now`，生产处理器在 `:169,184–185` 用真实时间正确拒绝了过期卡片。单项原样复现失败；仅在进程内补入 fixture 时间加一分钟，完整原测试函数的全部断言通过。未改源码或测试。修复应给测试注入一致时钟，保留生产过期检查。

因此当前本地快照仍不能表述为全部门禁已绿，但这个失败不支持业务功能回归的判断。应先修正该测试再建立重构基线。静态检查和合成测试也不证明真实平台、Muse 或模型质量已经验收。

## 技能保留、合并与降级建议

| 对象 | 当前职责与消费者 | 建议 |
|---|---|---|
| `skills/job-hunting/SKILL.md` | 宿主总入口，58 行 | 保留为薄入口；明确当前可执行路线，减少重复阶段描述 |
| `skills/job-hunting/optimizer/SKILL.md` | 简历路由、证据边界、L0–L3，38 行 | 保留；明确现有 lens 路由与未来能力图的区别 |
| `skills/jd-grounded-template-tailoring/SKILL.md` | 保留用户 Word 版式的定向改写，51 行 | 保留独立职责，补齐主入口路由和分发方式 |
| `message-generation.md` | 全消息类型的事实与审批规则 | 保留通用规则，引用唯一的首招政策 |
| `greeting-writing.md` | Personal AI 等宿主的起草操作手册 | 保留薄操作说明，减少重复政策正文 |
| `greeting-ai.md` | Codex 模型生成、复核的运行时政策 | 保留契约专用部分；公共规范与其他入口同源 |
| OSS 研究、历史 specs、旧宿主说明 | 来源许可、历史决策与兼容资料 | 移出默认任务上下文；归档前查明代码、测试及版本摘要依赖 |
| 本机旧 `job-hunt-patrol` | 私有旧工作流，部分规则与当前仓库不同 | 从当前 Codex 默认路线降级或改成明确的兼容入口；不要自动覆盖其他宿主既有流程 |

### 1. 最优先：安装副本与当前仓库已经不一致

`~/.agents/skills/job-hunting` 是普通目录副本，未与仓库同步：

- 安装版 `SKILL.md:43` 仍要求“从话术库挑句子”；仓库版 `skills/job-hunting/SKILL.md:43` 要求全文生成。
- 安装版缺少 `greeting-ai.md`、`preference-memory.md`、`worker.md`，入口、能力目录和两篇旧招呼文档也不同。
- `~/.agents/skills/job-hunt-patrol/SKILL.md:22` 允许多个会话同时发送；`:28–30` 保留固定结构、120 字和类别模板。
- 当前仓库 `capability-catalog.md:76` 要求每站一个发送租约，`greeting-writing.md:7–15` 要求自由全文生成。

影响：即使 Python 主流程通过测试，新会话仍可能先读取旧技能，从而生成不符合当前约定的内容或选择错误工作流。确定性门禁应继续拦截不合法操作，但入口本身也需要纠正。

建议：为每个受支持宿主显式选择一份版本化发行包，显示代码和政策摘要；旧运行固定旧版本，新运行使用新版本。增加安装副本与发行清单的一致性检查。不要只同步一个 `SKILL.md` 而留下旧 references。

### 2. 策略文档是运行时依赖，不能直接删除

实际消费者包括：

- `src/jobagent/reasoning/prompts.py:26–83` 按 prompt ID 读取当前阶段所需的策略正文。
- `src/jobagent/optimizer/tailoring.py:65` 读取选定视角的政策。
- `src/jobagent/bridge/greeting_generation.py:17,76–85` 只读取 `greeting-ai.md`，再把正文送入隔离的模型调用。
- `src/jobagent/evals/versioning.py:12–17` 把消息、对话、巡检规则纳入版本摘要。
- `src/jobagent/harness/runtime.py:10–23` 把整个 skill 树的相关文件纳入运行指纹。
- `src/jobagent/harness/service.py:81–84,120–123` 在指纹变化时拒绝恢复原运行。

合并招呼政策时，目标应是“一份公共政策 + 薄宿主说明 + 各模型输出契约”。必须由构建器实际拼装政策，并绑定组合后的摘要；仅在 Markdown 留一个链接，并不会让禁用工具的模型自动读到被引用的文件。

整理文档应作为明确的版本升级，不能为了兼容旧运行而删掉摘要检查，也不能让旧审批自动覆盖新正文或新政策。

### 3. 简历渲染路线和打包范围需要统一

- 主 `SKILL.md:14,42`、`rendering-ats.md:5–7`、能力目录 `:62` 仍将外部 `resume-builder` 作为默认路线。
- `resume-pipeline.md:53–69` 与能力目录 `:194` 已提供本地 `harness render`。
- 固定母版技能又提供 `TemplatePatch` 路线。
- `scripts/build_skill.py:24` 与 `pyproject.toml:66` 仅打包 `skills/job-hunting`，新增的固定母版技能没有随该独立包或 wheel 分发。

建议使用一张决策表：用户指定现成 Word → template patch；结构化新稿 → harness render；明确选择外部模板 → 对应外部 renderer。三条路线共用事实、独立复核和成品检查门禁。模板技能应明确作为独立分发依赖，或纳入主包并修正路径。

## 渐进式披露：已有基础，数据层仍需补齐

已有机制：优化器入口定义 L0 元数据、L1 当前能力、L2 去重策略、L3 任务数据；`reasoning/prompts.py` 按阶段组装规则；`optimizer/routing.py:22–27` 每次只选一个视角政策。

但两张优化器索引共 18 条记录中的 8 个 capability 仍缺 Phase 2 adapter。`optimizer/index.py` 实现静态加载、校验和稳定摘要，生产调用主要来自 `cli/optimizer.py` 的 `capabilities` 查询。当前 `tailor` 并未通过通用注册表动态执行。应保留真实状态说明，不为凑齐框架而一次性实现所有 adapter。

### 4. 默认简历路径没有有效缩小证据集

`optimizer/base_resume.py:46–61` 将全部已确认证据构成母版；`optimizer/context.py:16,37` 又将母版引用全部列为必需；`optimizer/tailoring.py:75–76` 同时传入完整母版和这些证据。

用合成资料执行默认组合：两条证据分别为 Python 服务与法国诗歌，JD 只有 Python，结果两条均入选、`omitted=[]`。因此选择器存在，但默认母版组合会让它保留全部确认事实。这是静态调用链与合成实验支持的结论，并未测量真实模型的 token 或质量变化。

建议区分完整母版归档与本岗位工作集：先选择相关条目和事实摘要，再按 ID 加载原始证据。完整母版留给最终 diff、遗漏检查与追溯。不能用字符截断代替选材，也不能删掉已知冲突或更正。中文关键词选择需要单独验证；当前 `\w+` 集合交集不等于中文语义检索。

### 5. 招呼上下文按条数封顶，仍可能很大

`bridge/greeting_context.py:208–252` 读取候选人全部 Evidence、数据库全部岗位，并把最多 16 条历史完整 JD 带入请求；定向稿也走这条路径。全部岗位读入内存，不代表全部岗位都传给模型，两者应区分。

`outreach/generation.py:41–60` 把同一完整请求交给生成和独立复核；修订还会再次使用。`bridge/codex_runner.py:71–72` 最终限制输入为 256,000 字节。条数限制无法保证满足该字节预算。

建议按场景构建不可变上下文包：

- 定向稿：完整目标 JD、相关已确认事实、必需冲突与更正、适用偏好。
- 通用稿：有来源的方向摘要，必要时再加载支持该方向的历史 JD。
- 复核：与生成使用相同事实、JD、偏好和政策快照，并独立检查全文的漏报主张。
- 记录已加载的资源 ID、版本、摘要、字节量或实际 token、选择原因与省略范围；预算不足时继续检索或明确停止，不静默裁掉证据。

## 代码层优先拆什么

### 6. 把 CLI / bridge 的用例编排抽为共享服务

具体耦合证据：

- `cli/jobs.py` 为 1,087 行，`search_plan:570` 和 `triage:661` 承担配置、偏好刷新、模型选择、筛选、清单生成与持久化。
- `cli/jobs.py:17` 直接导入 `cli/greetings.py` 的三个私有帮助函数。
- `cli/optimizer.py:386–405` 的验证、diff、变体组装与 `optimizer/tailoring.py:97–113` 基本重复。
- `bridge/feishu_approval.py:152,300` 与 `bridge/feishu_paged_approval.py:59,167` 存在双向延迟导入。
- `bridge/worker.py:78–160` 同时处理编排、SQL、事务和领域服务调用。
- `bridge/greeting_context.py:120–180` 与 `bridge/preference_memory.py:199–317` 各自读取并验证卡片反馈，历史兼容与严格绑定的差异没有通过明确接口表达。

建议逐步抽 `TriageService`、共享简历组装服务、招呼上下文准备、经过来源核验的反馈读取接口。CLI 保留参数与输入输出转换；模型、飞书、SQLite 各自作为适配器。先抽最小职责，不先大规模搬目录。

`conversation/service.py` 虽有 739 行，但仍保持领域隔离；等下一次相关改动再拆状态推导、回复门禁和提醒策略，优先级低于前述问题。

旧飞书卡有实际兼容消费者：`feishu_approval.py:152–155` 按分页状态分流，新卡也保留双份状态登记。不能因 Personal AI 不调用本机桥，就直接判定旧卡和桥接代码可删除。

## ReAct 应放在哪里

ReAct 描述的是推理与行动交替、根据环境结果选择下一步的模式；渐进披露描述何时向模型提供哪些信息。两者可以配合，但引入 ReAct 本身不会解决政策重复、技能分发漂移或全量上下文。

推荐方向：保持模块化单体，外层使用有边界的 Agent 调度，内层保持确定性业务规则。

```text
Personal AI / Codex / Claude / CLI / MCP
                  ↓
共享用例编排 + 按阶段准备的上下文
  外层可按结果选择下一步检索、起草、复核或停止
                  ↓
现有 schemas + 领域服务 + 提供方端口
  证据确认、校验、审批、租约、发送门禁、审计
                  ↑
模型 / SQLite / 文件 / 平台 / 旧宿主适配器
```

模型可以提出下一步动作，程序校验该动作是否允许。事实确认、本人审批、发送授权与未知结果处理继续走现有服务。记录动作请求、工具结果和状态即可，不需要保存模型完整内部推理。

新默认入口已经是 Personal AI，见 `docs/personal-ai-migration-2026-10-27.md:7–11`。优先让共享核心可供不同宿主调用；宿主已有工具循环时，无需再在内部嵌套一套通用 Agent 框架。领域层保持无 LangChain / LangGraph 依赖。

## 推荐实施顺序与验收

| 阶段 | 改动范围 | 验收重点 |
|---|---|---|
| 0：可复现基线 | 定位当前 1 个失败，确认工作区与发布版差异 | 四道门禁绿；明确支持哪个宿主版本 |
| 1：入口和政策收敛 | 安装版本、招呼公共政策、渲染路由、模板分发、过时说明 | 从全新安装调用任务，命中当前政策；旧运行仍有对应版本可恢复 |
| 2：实际上下文选择 | 简历工作集、招呼场景输入、上下文预算与版本追踪 | 无关事实不再默认全载；相关证据、更正和反证不丢；生成复核版本一致 |
| 3：用例服务抽取 | CLI 私有函数耦合、重复组装、反馈读取、卡片适配边界 | 旧 CLI 行为与摘要边界不变；失败、过期审批、重复任务和未知结果路径通过 |
| 4：按需扩展 Agent 调度 | 只在真实任务需要动态步骤选择时增加有限动作集合 | 步数有界；无法满足条件时停止；模型无权批准或绕过门禁 |

成本最低的“只改文档”能解决部分漂移，无法处理上下文和编排重复；全量换框架的回归范围最大，目前没有收益证据。建议选择中间路线，每次一个关注点，先写行为测试，再重构并跑全套门禁。

收益应以路由正确率、加载的实际 token、证据遗漏率、独立复核拒绝率和耗时衡量；目前没有性能基准，不能承诺具体降本百分比。

## 参考的一手资料

- [ReAct 原论文](https://arxiv.org/abs/2210.03629)：推理与环境行动交替的模式。
- [Anthropic：Agent Skills](https://www.anthropic.com/research/equipping-agents-for-the-real-world-with-agent-skills)：元数据、技能正文、按需资源的逐级加载，以及确定性代码与技能的配合。
- [Anthropic：Context engineering](https://www.anthropic.com/research/effective-context-engineering-for-ai-agents)：轻量引用、按需读取、混合检索与上下文管理。

以上用于解释设计模式；具体重构建议来自本工作区的调用链、文件比对和测试。
