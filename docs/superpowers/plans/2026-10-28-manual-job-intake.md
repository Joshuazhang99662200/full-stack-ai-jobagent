# 人工加岗闭环 Implementation Plan

> 当前会话按executing-plans逐项执行，遵守测试先行。用户已批准设计与2/3成熟度；在既有隔离工作区的新codex分支工作，不修改桌面原仓库。

**Goal:** 聊天人工入队可恢复推进到完整JD、独立草稿复核与下一轮有据查询。
**Architecture:** schemas定义契约，jobs纯规则，storage负责追加式队列和真实对象装配，CLI对接Muse动作与私有文件。
**Tech Stack:** Python3.11+、Pydantic、SQLite、Typer、pytest。

## Global Constraints
- 复用user_added与2独立公司可探索/3稳定，岗位兴趣和文案批准分离。
- 保持3查询/20详情尝试/每日最多50详情预算；发送只能走既有审批、租约与审计。
- 不从JSON布尔done推进：快照、特征、批准、计划必须读取真实对象；JD变化令派生产物过期。
- 无真实Muse权限时只声明合成接线验证；宿主网页与模型仍显式交接。
- 同一私有SQLite是状态权威；活跃词库MD存储为不可变版本和事务指针，外部MD是可导出视图。
- 所有新增命令同步capability-catalog；完成后全套pytest、Ruff、mypy、diff检查并提交PR。

## Task 1: 持久入队与恢复
Files: schemas/job_intake.py、jobs/job_intake.py、storage/job_intake_repository.py、migrations/0018_job_intake.sql；tests/jobs/test_job_intake.py、tests/storage/test_job_intake.py。
Interfaces: IntakeRequest、IntakeRecord、IntakeCommand；repository.enqueue/get/list_records/update；纯next_actions。
- [x] 写失败用例：URL/列表编号/卡片入口、缺列表版本、幂等、冲突、同岗位新消息合并、候选人隔离、CAS、中断恢复。
- [x] 运行新测试确认缺少模块导致预期失败。
- [x] 实现身份/快照/双分支状态与持久事件，新增迁移18并更新版本断言。
- [x] 验证真实SQLite并发末位只能有一个赢家。
Example assertion:
~~~python
assert repo.enqueue(request, now=now).intake_id == repo.enqueue(request, now=now).intake_id
~~~

## Task 2: 快照、草稿与兴趣信号接线
Files: storage/job_intake_service.py、schemas/job_intake.py；tests/storage/test_job_intake_service.py。
Interfaces: resolve、attach_snapshot、factorize、submit_draft、review_draft、attach_batch、set_interest；使用existing job/snapshot/batch。
- [x] 失败测试：身份错配/partial阻断/预算不匹配/JD变化失效/已联系转对话；明确兴趣user_added、不明确无偏好。
- [x] 实现从真实库核验产物引用，接既有factorize与原文校验；特征和草稿两个分支各自保存。
- [x] 草稿独立复核绑定正文摘要、snapshot与不同作者/复核运行引用；复核是宿主判断，记录不能认证身份。
- [x] batch绑定现有outreach清单，不自动批准或发送；新JD使旧草稿不能交接。
Example assertion:
~~~python
assert "fetch_full_jd" in next_actions(repo.get(key, candidate))
assert "generate_greeting" not in next_actions(partial)
~~~

## Task 3: 域学习、活跃计划与下一轮领取
Files: storage/intake_strategy.py、schemas/job_intake.py；tests/storage/test_intake_strategy.py。
Interfaces: rebuild、active、claim、record_search；从同域全部最新完整快照与持久本人信号装配。
- [x] 失败测试：保留旧样本、兴趣撤回/重复不加权、候选/冷却/入选区别、未获授权发送、策略CAS。
- [x] 保存不可变MD/plan，再事务更新活跃指针；中断只留未激活版本，无半写MD。
- [x] claim绑定实际sourcing run和候选人/来源，幂等返回同计划；record_search只引用既有预算query成功结果，不能把计划当已执行。
- [x] 两轮合成验收：三个人工兴趣岗位形成稳定特征，下一轮领取新计划，只有实际成功查询写执行记录。
Example assertion:
~~~python
assert strategy.claim({"candidate_id": candidate, "domain": domain, "run_id": run_id}, now=now)["plan"]["version"] == active["plan"]["version"]
~~~

## Task 4: CLI、宿主协议、全套门禁与PR
Files: cli/job_intake.py、cli/app.py、能力目录、hosts/personal-ai三文件、技能路由、docs。
- [x] CLI失败测试后接入intake enqueue/resolve/snapshot/factorize/draft/review/batch/interest/next/status/list/history/control/strategy/active/claim/record-search。
- [x] 结构化错误不泄露私有输入；help和能力目录双向一致。
- [x] 明确指令模板：聊天插入立即入队，每次交互/轮询恢复未完成动作，下一轮必须claim新计划；报告真实版本/候选状态。
- [x] 全套门禁通过后分关注点提交，推送codex分支并创建和附加PR，不合并。
Run:
~~~text
python -m pytest -q
python -m ruff check .
python -m mypy src/jobagent
git diff --check
~~~

最终验证：956 passed；Ruff通过；Mypy 149个源码文件通过；git diff --check通过。已创建并附加 [PR #5](https://github.com/Joshuazhang99662200/full-stack-ai-jobagent/pull/5)，未合并。
