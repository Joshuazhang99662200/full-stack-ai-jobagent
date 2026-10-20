# 求职 Harness Skill 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 将当前求职技能树交付为 Codex 与 Claude Code 都能安装、初始化、恢复和操作的独立 skill 包。

**Architecture:** Python 服务执行确定性契约、主张覆盖与状态保存；宿主负责推理、用户交互与外部能力。分发构建白名单复制源代码及技能资源，生成摘要清单，启动脚本不依赖仓库工作目录。

**Tech Stack:** Python 3.11+、Pydantic、Typer、SQLite、stdlib 文件锁与原子写入、pytest。

## 全局约束

- 不提交或推送；所有领域类型在 schemas；无平台 SDK 依赖进入领域。
- 只有 CandidateEvidenceService.confirm 能提升职业证据；投递逐份审批，状态文件不能授予审批。
- 不新增批量投递编排、密码输入、系统常驻服务或真实外部发送。
- 私密数据写入用户工作区，分发采用源码与资源白名单。
- 安装、浏览器与调度能力明确探测与降级；保留已有上下文路由。

## 任务 1：独立分发包与启动脚本

文件：scripts/build_skill.py、skills/job-hunting/scripts/bootstrap.py、tests/harness/test_distribution.py。

- [x] 先写复制到干净目录仍可启动、篡改拒绝、拒绝覆盖已有 skill 的测试。
- [x] 运行 `python -m pytest -q tests/harness/test_distribution.py`，确认缺少构建脚本失败。
- [x] 构建接口：`build_skill(destination: Path, host: str) -> Path`。白名单复制 `src/jobagent` 的 .py/.sql/.json/py.typed、完整技能树和许可证，写文件 SHA-256 清单。
- [x] 启动接口：`python <skill>/scripts/bootstrap.py --check`；`--setup` 建私有虚拟环境；`-- <jobagent argv>` 使用私有 Python 或当前已满足依赖的 Python。清单校验失败不得执行 runtime。
- [x] `--host codex|claude-code` 构建相同核心，安装位置由 destination 决定，不修改宿主全局配置。
- [x] 运行定向测试，确认包独立于 cwd，未携带候选人状态。

```python
def test_standalone_skill_runs_without_checkout(tmp_path):
    skill = build_skill(tmp_path / "installed" / "job-hunting", "codex")
    result = subprocess.run([sys.executable, str(skill / "scripts/bootstrap.py"),
                             "--", "optimizer", "capabilities"], cwd=tmp_path,
                            capture_output=True, text=True)
    assert result.returncode == 0
```

## 任务 2：运行契约、隔离状态与租约

文件：schemas/harness.py、storage/harness_store.py、harness/service.py、cli/harness.py、tests/harness/test_runs.py、tests/cli/test_harness.py。

- [x] 写 start/resume/checkpoint、跨宿主租约拒绝、产物变更拒绝、路径越界与无效契约测试。
- [x] 运行测试确认未实现失败，再实现类型化输入输出。
- [x] 每运行唯一 RUN_ ID；每 artifact 保存相对路径、SHA-256、契约名。锁用独占创建，状态用临时文件加 os.replace。resume 校验已保存产物，租约到期仅允许显式恢复，无自动外部重发。
- [x] CLI 采用 `harness start/status/resume/checkpoint/release`，宿主必须携带 session ID；checkpoint 只记录状态，不能审批或发送。
- [x] 新命令同步能力目录。执行实际跨宿主交接和恢复测试。

```python
run = service.start(candidate_id="CAND_001", host="codex", session_id="session-a")
service.release(run.run_id, "session-a")
resumed = service.resume(run.run_id, host="claude-code", session_id="session-b")
assert resumed.run_id == run.run_id
```

## 任务 3：主张覆盖、独立复核与 handoff

文件：schemas/optimizer.py、optimizer/verification.py、optimizer/tailoring.py、optimizer/context.py、reasoning/handoff.py、reasoning/prompts.py、cli/optimizer.py。

- [x] 修改空台账测试为拒绝，并先写未覆盖条目、无关证据、旧复核摘要和并发 handoff 测试。
- [x] 实现主张与条目双向覆盖；独立 ClaimReviewSet 必须绑定当前草稿和证据摘要，生成标签不能替代复核。
- [x] `optimizer review` 发独立复核请求，`assemble --review` 消费该产物；缺复核时输出 review_required 并阻断放行，宿主按协议调用 review。将 TailoredDraft 与 LensSelection 迁入 schemas。
- [x] handoff 使用独立请求目录和结构化 resume_argv，路径带空格也可正确恢复；assemble 的来源摘要包含实际策略与视角。
- [x] 相关证据按 JD 与母版引用确定性选择，并记录遗漏项。所有输出命令与目录一致。
- [x] 运行优化器、推理与 CLI 定向测试。

```python
report = ClaimVerifier().verify(ClaimLedger(), [])
assert not report.passed
assert report.evidence_coverage == 0
```

## 任务 4：PDF 与实际交付边界

文件：harness/pdf.py、schemas/harness.py、cli/harness.py、connectors/liepin_delivery.py、对应 tests。

- [x] 先写 PDF 文本一致性/页数、不能向平台传递已审批附件时停止的失败测试。
- [x] PDF 检查消费已通过验证的 ResumeVariant 和外部渲染 PDF；拒绝缺文字、缺条目、超页，不提供未经验证的 PDF 成功结论。
- [x] 猎聘连接器无法传定制附件与消息时，明确人工提交，不将仅 job apply 调用称为定向简历交付。
- [x] 汇总以实际审计记录与产物状态为准；无结果记录保持 unknown，不通过重发推测结果。
- [x] 运行投递、PDF 和 CLI 定向测试。

## 任务 5：宿主协议与完整验收

文件：技能入口与 references/harness.md、references/hosts/*.md、README、AGENTS.md、能力目录、.gitignore、docs/harness-skill-design.md。

- [x] 补首次调用与恢复协议、两种宿主安装命令、调度/登录/渲染降级、逐份审批、结果汇总。
- [x] 更新过期阶段描述；忽略全部 .jobagent 私密运行产物。
- [x] 以合成数据完成独立安装 → 初始化 → handoff → 复核 → PDF 检查 → preview → 逐份审批 dry-run → 审计的验收。
- [x] 执行 `python -m pytest -q`、`python -m ruff check .`、`python -m mypy src/jobagent`、`git diff --check`。
- [x] 生成两种宿主的分发 zip 并校验；明确真实宿主、平台与调度未实测项。保持未提交状态。

