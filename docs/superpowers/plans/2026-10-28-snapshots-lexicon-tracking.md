# JD快照、词库与已发送跟踪 Implementation Plan

> **For agentic workers:** 按executing-plans在当前codex分支执行，每项遵守测试先行。用户已授权最终PR；分批提交，不合并main。

**Goal:** 提供能在Muse私有环境运行的快照、因子化、词库组合与只读跟踪能力。
**Architecture:** schemas定义类型，jobs纯算法，storage追加历史，CLI装配已有批准/审计/对话记录。
**Tech Stack:** Python3.11+、Pydantic、SQLite、Typer、PyYAML、pytest。

## Global Constraints
- 沿用默认薪资重叠规则与3/20/50预算。
- 不改既有批准/租约/发送/审计语义，不调用模型或招聘网站，不提交私有数据库与正文。
- 所有变更均可追溯到快照、用户反馈或真实来源引用。

## Task 1: 快照、特征与导入
- [x] 确认844项绿色基线，提交上一阶段。
- [x] 定义schemas/jd_snapshot.py与schemas/lexicon.py的基础类型。
- [x] 写失败测试：相同内容多查询发现、JD变更/恢复、ID冲突、摘要不抽取、10组合成样本与否定/别名/无原文回退。
- [x] 实现jobs/jd_snapshot.py、jd_features.py、jd_factorization.py及storage/jd_snapshot_repository.py。
- [x] 新迁移15保存快照、发现、特征和不可变词库版本；接jobs import-observations/add-jd，原匹配顺序不变。
- [x] 跑快照、特征、导入及迁移测试，更新版本断言，提交。

## Task 2: Markdown词库与组合查询
- [x] 写失败测试：无版本拒绝、空模板、往返/手改、未知词成熟度、公司独立性、同输入版本幂等、三条方向拒绝后移、预算/冷却/基线回退、设计域样本。
- [x] 实现jobs/lexicon.py纯解析/序列化，扩展query_derivation.SearchQueryDeriver与search_learning的绝对重算。
- [x] 接CLI的snapshot/factorize/lexicon-update/lexicon-show/combinations，新增能力目录入口。
- [x] 保留MD版本和来源摘要，不自动覆盖本人文件；完成模板和格式规范，提交。

## Task 3: 已发送状态机与私有历史
- [ ] 写失败测试：无批准/审计或回读不一致拒绝；sent→awaiting→replied→screening/interview；14天与4检查AND；非法跳转/重复证据/并发版本拒绝；放弃/岗位关闭归档；异常暂停、明确恢复；关闭不再到期。
- [ ] schemas/sent_tracking.py与jobs/sent_tracking.py实现纯状态机和日程；storage/sent_tracking_repository.py追加迁移17，CAS历史不可改写。
- [ ] CLI读取已有outreach批准和审计校验回读；新一轮等待读取既有conversation批准/发送事件；预执行状态仅为门禁投影，不创造发送权。
- [ ] 提供状态/到期/历史/结果模式报告，报告不改变词库；完成真实SQLite/CLI组合测试后提交。

## Task 4: 文档、全套门禁与PR
- [ ] 更新主技能、能力目录、Personal AI任务/记忆协议、README、换域和迁移说明，明确所有附件修订与实际能力限度。
- [ ] 全套pytest、ruff、mypy、git diff --check；检查无真实JD/已发正文/候选人数据，确认旧桥无新增依赖。
- [ ] 推送codex功能分支，通过GitHub工具创建一个PR并附到当前聊天；PR回答六项映射、接线点、非法转移、版本/回滚、私有数据位置和设计域演练结果。
