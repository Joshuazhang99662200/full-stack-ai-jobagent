# Muse回执 P0/P1 Implementation Plan

> 用户要求基于PR5继续更新，回执作为需求数据和验收参考。当前按writing-plans、systematic-debugging、TDD分步执行；P0/P1分支与PR分开，不删除桥接，不操作Muse私有任务或真实招聘站点。

**Goal:** 提供可执行迁移、正式跟踪补建/登录接线、显式扩量政策、全文回填与私有文案diff机制，并给出可复查的宿主验收报告。
**Architecture:** schemas类型权威；jobs纯规则；storage事务和真实账本装配；CLI薄适配。保留原批准、租约、发送语义。
**Tech Stack:** Python、Pydantic、SQLite、Typer、pytest。

## Global Constraints
- 956项PR5基线；所有功能RED→GREEN，最终pytest/Ruff/mypy/diff。
- 默认3查询/20详情/每日50不变；显式muse-expanded-v1政策可12查询/每查询前10列表/每轮60详情/每日240。缺参数或超限报错，不静默裁减。
- 薪资宿主显式upper_bound；未知/不可比REVIEW。
- 旧摘要一律partial，未知时间和发送证明不补造，人工来源不伪造query_hit。
- 真正40行和8条数据不在本地，提供参数化工具和合成40行验收；真实执行保持unverified。
- 接受文案不代表喜欢岗位；user_added复用人工兴趣，human_picked是处理来源/明确选择的独立字段，不再创造同义正例。
- A/B/C不进入规则；推广必须本人逐条确认；无自动调词权重。
- P2只准备删除与两轮验收清单，不执行浏览器、发消息或创建任务。

## Task P0-A: 显式预算政策
Files: schemas/sourcing.py、lexicon.py、job_intake.py；cli/sourcing.py；storage/sourcing_repository.py；tests/jobs/test_host_budget.py、tests/cli/test_sourcing.py。
- [x] RED：12查询/60详情/240每日显式政策，缺参拒绝，旧默认保留；预算耗尽与失败计量。
- [x] GREEN：冻结政策与实际限额，计划/claim能处理12条，查询前10观察与跨查询去重由宿主真实观测执行。
- [x] 验证薪资四组及不可比，完整门禁后单独提交。

## Task P0-B: 40行迁移与投影
Files: schemas/host_migration.py、storage/host_migration.py、cli/host.py、迁移19；tests/storage/test_host_migration.py。
- [x] RED：显式字段映射、输入恰好40条、备份/幂等/冲突、同岗合并的行映射与精确校验、失败不改原库、可回滚。
- [x] GREEN：在临时副本迁移并校验后原子替换；原始行哈希与legacy映射追加保存，partial/待证明发送保留，无占位JD或伪审批。
- [x] 提供inspect、migrate、verify、project、rollback命令；投影不写回输入台账。

## Task P0-C: 迟到跟踪与页面沉降
Files: schemas/sent_tracking.py、jobs/sent_tracking.py、cli/tracking.py、storage/sent_tracking_repository.py；schemas/host_checks.py、jobs/host_checks.py、storage/host_checks.py；tests。
- [x] RED：错过第1天不补次数，显式下一轮首查，补查至少隔一天，缺发送证明不正式建档。
- [x] RED：两站/消息与搜索独立三态；占位重载一次仍未知；登录跳转立即需通知并暂停消息跟踪；不把徽标当回复。
- [x] GREEN：复用原sent证明与状态机，新增迟到元数据和页面观察接线，不改发送权。

## Task P0-D: 宿主清单与两轮报告
Files: schemas/host_checks.py、storage/host_reports.py、cli/host.py、skills参考与hosts三契约、docs。
- [x] RED：计划≠执行，query_hit仅搜索来源计分母，partial不入策略，缺字段/零样本不冒称100%，两轮报告可验证。
- [x] GREEN：报告真实计划/执行/新入库/草稿/版本/跟踪简表/三态/未完成项；无法验证项明确unverified。
- [x] 全套门禁，P0推送并创建基于PR5的独立PR，附到聊天。

## Task P1-A: 全文回填与版本
Files: storage/host_migration.py或独立backfill.py、cli/host.py、测试。
- [x] RED：优先ID由私有配置传入；列表/摘要仍partial；真实新全文追加原文与谱系链接，保留旧legacy原文，无未知查询伪造。
- [x] GREEN：生成回填清单并校验现有完整snapshot/预算/来源，JD变化保留历史并失效派生物。

## Task P1-B: 文案diff机制与人工推广
Files: schemas/message_diff.py、jobs/message_diff.py、storage/message_diff_repository.py、cli/host.py、迁移20与测试。
- [x] RED：全文哈希绑定、6类有据提案、多类与未知、同稿/恢复原稿不计偏好、3独立岗位阈值。
- [x] GREEN：私有输入保存摘要和差异位置，类别提案不是已确认事实；推广只接受本人确认过的准确规则与评估版本。
- [x] 测试证明不改岗位偏好/词库/查询，A/B/C无预置，分开P1 PR。

## Task P2: 清单，不执行
- [x] 输出桥接删除阶段与rg/pytest命令，先迁rewrite再按依赖删除；不做任何实际删除。
- [x] 宿主两轮验收命令/模板，真实网站与任务由Muse执行；最终报告区分代码通过与真实未验收。


## Delivery evidence

P0: commit516341b / PR #6，998 passed；P1: commit0d901e7 / PR #7，1021 passed。两次Ruff、strict mypy与diff检查通过。PR顺序为 #5 → #6 → #7，均未由本任务合并。P2勾选仅表示计划与检查入口已交付，未执行桥接删除或真实两轮验收。真实40行/8条/全文回填、宿主通知和恢复仍unverified；缺逐条证明保留proof_pending。
