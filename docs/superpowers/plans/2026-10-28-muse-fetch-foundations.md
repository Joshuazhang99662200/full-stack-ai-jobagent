# Muse 寻源策略基础修订 Implementation Plan

> **For agentic workers:** 使用 executing-plans 在当前独立 worktree 内逐项执行，按 TDD 验证。不提交、不推送。

**Goal:** 落地已确认的反馈拆分、薪资区间重叠比较和真实读取预算，并更新 Muse 协议。
**Architecture:** schemas 定义输入输出；搜索学习和薪资保持纯领域逻辑；独立 SQLite 适配器原子保存预算预占及追加结果；薄 CLI 只装配和输出 JSON。
**Tech Stack:** Python 3.11+、Pydantic、Typer、SQLite、pytest。

## Global Constraints

- 基准 38afd89，保留来源每日详情上限 <=50。
- 不修改 outreach、applications、candidate 或发送授权契约。
- 真实数据只留私有区；不接浏览器、不调用模型。
- 兼容历史 signal 重放；不把文案确认视为岗位偏好或发送批准。

## Task 1: 薪资与反馈（独立可测）

**Files:** schemas/job_intelligence.py、schemas/search_learning.py、jobs/hard_filter.py、jobs/search_learning.py，及各自 tests。
**Interfaces:** CandidateFilterContext.compensation_comparison；SearchSignal.job_preference / message_feedback；learn_search 保持原签名。
- [x] 基线 python -m pytest -q 通过后写测试。
- [x] 测试默认 upper_bound 接受跨底线与等值区间、拒绝上限不足；lower_bound 仅显式启用，未知与不可比 REVIEW。
- [x] 测试 feedback 的岗位喜欢+改文案、仅文案不学习/不覆盖、neutral、同时间冲突与异用户拒绝。
- [x] 运行新增测试，确认因当前行为或缺契约失败，再实现最小修改。
- [x] 运行 tests/jobs/test_hard_filter.py 和 tests/jobs/test_search_learning.py，确认全部通过。

## Task 2: 预算账本与公开入口（独立可测）

**Files:** 新建 schemas/sourcing.py、jobs/sourcing.py、storage/sourcing_repository.py、storage/migrations/0014_sourcing_budget.sql、cli/sourcing.py、tests/jobs/test_sourcing.py、tests/storage/test_sourcing_repository.py、tests/cli/test_sourcing.py；修改 storage/database.py、cli/jobs.py 及能力目录。
**Interfaces:** SourcingRun、SourcingAttemptRequest、SourcingAttempt、SourcingResult、SourcingBudget、SourcingPermit；SqliteSourcingRepository.start_run / reserve / complete / budget。
- [x] 写 CLI 测试：jobs sourcing-start / sourcing-reserve / sourcing-result；查询和详情分别计量，缺岗位信息拒绝。
- [x] 写真实 SQLite 测试：失败不退额、幂等与冲突、轮次额度冻结、当日并发最后名额、旧轮次午夜拒绝、gate 后停止、旧岗位记录不重复计入。
- [x] 运行测试观察缺实现失败；再新增 schema、纯预算判定、v14 迁移和仓储原子事务。
- [x] 薄 CLI 从 registry 读取上限；时间由程序生成，不相信宿主回填历史时钟；与旧 sourcing-budget 输出兼容。
- [x] 更新数据库版本测试到14，跑预算、CLI、迁移与能力目录测试。

## Task 3: 宿主协议与最终验收

**Files:** README.md、hosts/personal-ai/{README,memory,tasks}.md、skills/job-hunting/references/{browser-sourcing,job-intelligence,capability-catalog}.md，以及 docs/muse-fetch-strategy-2026-10-28.md。
- [x] 写清新反馈 JSON、显式薪资模式、预占到结果的调用顺序与预算单位。
- [x] 文档规定稳定/探索/回访、有限软词调整、先列表后详情、失败停站、零结果私有报告和检查点。
- [x] 明确本次与后续快照/词库阶段的能力边界，不把提示词写成代码已实现。
- [x] 完整运行 pytest、ruff check .、mypy src/jobagent、git diff --check。
- [x] 审阅 diff 确认审批相关模块无变化，保存门禁结果，交付可审阅代码与说明。

## 完成记录

基线800 passed；首轮836 passed，本次薪资修正后844 passed，累计新增44个用例。Ruff、Mypy（129个源码文件）、git diff --check均通过。审批/发送生产实现无改动；审计测试仅将迁移版本断言13更新为14。未提交或推送，工作区保留供审阅。
