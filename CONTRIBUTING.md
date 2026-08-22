# 贡献指南

## 环境

需要 Python 3.11+。

```bash
python -m pip install -e ".[dev]"
```

## 质量门禁

提交前按顺序跑完这四条,全部通过才算完成:

```bash
python -m pytest -q
```

```bash
python -m ruff check .
```

```bash
python -m mypy src/jobagent
```

```bash
git diff --check
```

mypy 配置为 `strict`。Ruff 行宽 100,启用 `E,F,I,UP,B,SIM,RUF`。

## 测试驱动

本项目采用测试先行:先写失败的测试,确认它以预期原因失败,再写实现。测试不是补交的证明材料,而是设计工具。

每个能力都要有独立测试。跨能力的编排测试放在 `tests/workflows/`。

## 不可违反的架构不变式

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

具体到代码:

- 领域模块不得 import Typer、SQLite、浏览器自动化、DOM 选择器、平台 SDK 模型、LangChain 或 LangGraph。
- 不可逆操作各自是独立能力,不得合并。搜索不能投递,预览不能审批,审批不能投递。
- 只有 `CandidateEvidenceService.confirm` 能提升 canonical Evidence,且必须有显式用户确认。
- 连接器把登录、CAPTCHA、验证、风控、平台变更翻译为 `USER_INTERVENTION_REQUIRED`,不得绕过或自动重试。

违反上述任意一条的 PR 不会被合并,无论测试是否通过。

## 新增一个能力

按这个顺序做,每步都有对应测试:

1. 在 `src/jobagent/schemas/` 定义类型化输入输出契约;
2. 在对应领域包实现服务,保持无隐藏副作用;
3. 在 `src/jobagent/cli/` 暴露命令,输出 JSON,错误走结构化信封;
4. 更新 `skills/job-hunting/references/capability-catalog.md` 的状态与入口。

第 4 步不是可选的。`tests/test_capability_status.py` 会双向断言目录中的命令集合与 Typer 实际命令树完全相等,漏更会直接失败。

## 优化器能力索引

`skills/job-hunting/optimizer/index/*.yaml` 是**契约数据,不是文档**。修改时注意:

- 每条 `description` 必须包含 `Outcome:`、`Trigger:`、`Excludes:`、`Output:` 四个标记,且 `Excludes:` 段落必须出现 `do not` / `only` / `cannot` / `never` 之一;
- 这些字段保持英文,由 `tests/optimizer/test_repository_index.py` 断言;
- 任何改动都会改变注册表摘要,请在 PR 中说明新摘要;
- 编译器绝不 import 被索引的入口点,不要为了"验证一下"而加动态 import。

## 文档语言约定

- 面向人的文档(README、`docs/` 顶层、`skills/job-hunting/**/*.md`)用**中文**。
- 代码、注释、docstring、测试名、提交信息主题行之外的标识符用**英文**。
- 技术标识符在中文行文中保持原样:`L0`–`L3`、`EVID_*`、`PASS`/`REVIEW`/`REJECT`、schema 类名、CLI 命令等。
- `docs/superpowers/` 下的 specs 与 plans 是带 commit 哈希的历史评审记录,**保持英文原样,不要翻译**。
- 两个 `SKILL.md` 的 frontmatter `description` 采用中英并列,以兼顾中英文查询的技能命中率。

## 提交与 PR

- 提交信息用 Conventional Commits 前缀(`feat:` / `fix:` / `docs:` / `test:` / `refactor:`),正文说明**为什么**,不只是改了什么。
- 一个提交一件事。不要把无关改动混进来。
- PR 中附上改动文件清单、测试证据,以及一句架构不变式自查结论。

## 绝对不要提交的内容

真实简历、真实联系方式、`.env`、SQLite 数据库、浏览器配置、会话令牌、生成的简历变体。这些路径已在 `.gitignore` 中,但请在 `git add` 前自行确认。复现问题时一律使用合成数据。

## 不会被接受的贡献

- 绕过平台登录、验证码、风控或反爬机制的代码;
- 移除或弱化人工审批门禁的改动;
- 把本项目改造成批量自动投递工具的方向性改动;
- 未经许可证核查就引入的上游代码——先更新 `skills/job-hunting/references/oss/source-manifest.yaml` 与 `docs/oss-review.md`。
