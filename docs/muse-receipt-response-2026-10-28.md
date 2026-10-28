# Muse回执处理结果与真实验收边界

基线为PR #5（cb5e301）；P0为codex/muse-host-p0 / PR #6，P1为codex/muse-host-p1 / PR #7。仓库侧提供可执行工具及宿主调用协议，运行中的Muse任务、网页、私有40行/8条数据没有被本次代码操作接触。

| 回执项 | 仓库交付 | 仍需Muse实际执行 |
|---|---|---|
| A 人工加岗/40行 | 原PR5三入口及CAS恢复保留；新增备份、字段映射、精确行校验、投影、受保护回滚 | 用真实私有队列迁移，回读全部原ID与链接，实际接入聊天/卡片/轮询 |
| B 已发8条 | 正式发送证明门禁保留；迟登记首查与漏查元数据；分站分页面登录状态、暂停及通知要求 | 逐条补原审批、正文、回读与时间证据；不足继续proof_pending，不能凭窗口造时间 |
| C 薪资/预算 | 显式upper_bound；默认也为upper_bound。扩展12/60/240为显式宿主档，默认3/20/50保留 | 更新实际调用参数并保存预算回执，遵守来源会话和风险限制 |
| D 全文回填 | 私有优先ID清单、观察/预算绑定、旧v0到正式全文谱系、JD变化失效派生 | 从真实详情补完整JD，搜索填真实query_hit，人工/推荐留null；此前partial未进策略 |
| E 文案diff | 六类位置证据提案、私有全文哈希、三岗位成熟度、原稿恢复排除、逐条本人规则确认/撤回 | 提供真实初稿与最终稿及分类证据；展示具体规则后取得本人原话，不用文案Accept替代 |
| F 两轮验收 | round-template/report/show/verify-rounds，实际查询归因扫描、计数与未完成项 | 两轮真实网页、私有状态恢复、单实例和通知送达；real_browser_verified仍false |

A/B/C假设没有进入规则、词库权重或查询计划。正文对比不证明已发送，人工选择/岗位偏好/文案反馈分开；个人事实与逐项投递审批不受学习信号替代。

物理事实源是宿主私有SQLite；全文在jd_snapshots，原发现归因在jd_discoveries，旧行与摘要在host_legacy_rows，谱系在host_backfill_links，diff在message_diff_events，规则与本人确认在message_rule_*。原始文件和数据库备份在私有库旁migration-backups。JSONL和MD是投影，不能作为第二套写入权威。

换域只替换该人的candidate/domain、已确认证据、硬条件、基础词、当前域词库、迁移字段映射和适用本人规则。设计域合成用例验证同一快照/特征/词库/组合流程；不改schema、预算、审批或跟踪算法。

接线顺序见 [P0宿主协议](../skills/job-hunting/references/muse-host-adoption.md) 和 [P1回填与差异](../skills/job-hunting/references/muse-backfill-and-diff.md)。旧桥接只准备 [独立删除计划](muse-bridge-removal-plan.md)，未执行删除。不要把代码测试通过标成真实40迁移、真实8条正式跟踪或真实两轮已完成。


代码验证：P0为998 passed，P1为1021 passed；Ruff、strict mypy（P1为160个source files）与git diff --check通过。审阅/合并顺序为 [PR #5](https://github.com/Joshuazhang99662200/full-stack-ai-jobagent/pull/5) → [PR #6](https://github.com/Joshuazhang99662200/full-stack-ai-jobagent/pull/6) → [PR #7](https://github.com/Joshuazhang99662200/full-stack-ai-jobagent/pull/7)，本任务未执行合并。
