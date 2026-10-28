# 已发送消息的观察与归档

只在需要查看已发消息、检查到期、记录真实新回复或结束跟踪时加载本页。日常寻源不必加载所有对话与历史正文。已落地命令见 capability-catalog.md；回复与简历仍按 conversation.md、hitl-approval.md 独立审批。

## 建档与证据边界

只有现有 outreach 的人工审批、绑定摘要和 sent 审计一致，且宿主提供的实际回读全文与获批缓存逐字相等，tracking start 才保存 sent → awaiting_reply 两条历史。也可引用既有 conversation 的 reply_approved + sent reply_result 建立新跟踪；需要同一岗位的缓存 URL。不能用客户端传来的 approved=true 或发送意图代替审计。

程序校验的是记录与提交回读的一致性，无法认证宿主浏览器或账号，也不能从旧 outreach record 推断真实网页已回读。sent_at 使用已有审计的 recorded_at，明确标 sent_time_basis=audit_recorded_at，可能晚于实际发送时间。未确认回读不建已发送跟踪；已有跟踪的新回复回读不一致则追加异常、暂停，不重发。

建档 JSON 例（所有正文只在私有区）：

~~~json
{
  "candidate_id": "CAND_DEMO",
  "tracking_id": "TRACK_DEMO",
  "audit_id": "OAUDIT_DEMO",
  "readback_text": "宿主实际读到的完整文本"
}
~~~

conversation 来源改用 conversation_id、reply_result_event_id，不能混用 audit_id。默认 tracking_id 从发送引用摘要生成，重复建档返回同一结果，同一发送不能绑定多个跟踪。

## 命令与事件

~~~text
jobagent tracking start <private-input.json> --database <private-db>
jobagent tracking pending <batch_id> --session <session_id> --database <private-db>
jobagent tracking event <private-event.json> --database <private-db>
jobagent tracking status <tracking_id> --candidate <candidate_id> --database <private-db>
jobagent tracking due <candidate_id> --database <private-db>
jobagent tracking history <tracking_id> --candidate <candidate_id> --database <private-db>
jobagent tracking report <candidate_id> --database <private-db>
~~~

pending 只投影既有未撤回批准与各站会话租约，仍检查原有平台节奏、当日叫停与上限；不取得租约、不创建跟踪、不执行发送。下一条执行仍调用 outreach next。其余跟踪命令只记观察和状态。

事件契约 TrackingEventInput 必填 event_id、tracking_id、candidate_id、expected_version、kind、observed_at（含时区）、observation_id、evidence_reference、evidence_kind。每次从 status 读取当前版本；同 ID 同内容重放幂等，不同内容冲突，旧版本不能覆盖新状态。观察必须按时间追加，不能来自未来。

~~~json
{
  "event_id": "TEVT_DEMO",
  "tracking_id": "TRACK_DEMO",
  "candidate_id": "CAND_DEMO",
  "expected_version": 2,
  "kind": "reply_confirmed",
  "observed_at": "2026-10-28T10:00:00+08:00",
  "observation_id": "OBS_DEMO",
  "evidence_reference": "CEVT_INBOUND_DEMO",
  "evidence_kind": "conversation_message",
  "conversation_id": "CONV_DEMO",
  "inbound_event_id": "CEVT_INBOUND_DEMO"
}
~~~

先通过 conversations inbound 保存实际消息。确认回复/初筛/面试/拒绝时，CLI必须从库读取该 INBOUND，匹配岗位、平台、会话、事件与时间。列表未读计数只能记 suspected_reply，不算回复。旧轮次消息不能触发新轮次。初筛需 asks_resume 或实际原文中的明确推进片段；面试需 interview_invite，拒绝需 declined。宿主必须忠实归类，不把自动摘要当真实推进事实。

| 当前状态 | 事件 | 结果 |
|---|---|---|
| 已批准未执行 | pending 投影 | approved_pending_execution；仅原门禁放行的下一条为 leased |
| 完整发送证明 | start | sent → awaiting_reply，保存两条历史 |
| awaiting_reply | reply_confirmed | replied，停止默认无回复检查 |
| replied | screening_confirmed | screening |
| replied / screening | interview_confirmed | interview |
| replied / screening / interview | reply_sent | 既有新批准回复结果且回读一致；replied 开启新 awaiting_reply，初筛/面试保持后续人工节奏 |
| awaiting_reply | no_reply | 有效检查 +1，满 14 天且满 4 次后 no_response_expired → closed |
| 跟踪中 | employer_rejected / job_closed | 拒绝或同 URL 岗位关闭证据 → 对应状态 → closed |
| 跟踪中 | user_abandon / queue_closed | 本人原话与来源 → abandoned_by_user → closed |
| 当前状态 | anomaly | 状态保持，paused=true，清除到期 |
| 暂停中 | resume | 本人明确恢复；不自动重发 |
| closed | 普通跟踪事件 | 拒绝恢复；新批准与新发送另建记录 |

不能 awaiting_reply → interview；不能无回读建档；不能关闭后复活旧等待。归档保留 abandoned_at、abandon_reason、outcome 与完整版本链，停止到期检查，不删除发送事实。用户从队列移除需宿主追加 queue_closed，本项目没有新增 Muse 队列事件总线。

## 日程与报告

默认从审计记录时刻起第 1、3、7、14 天只读检查，合并到用户已有搜索/巡检任务。程序不创建定时任务。漏查补查间隔至少一天，不能一次打开页面四遍凑数。满四次但未满14天等待第14天；满14天但不足四次继续有效补查。关闭、暂停、已回复、初筛、面试均不进入默认 due 列表。

报告分开列现状、下次检查、关闭时间与原因。no_response/rejected 的特征至少覆盖3个不同岗位才列观察模式，screening/interview 单列正向观察；changes_search_weights 永远为 false。无回复不证明方向不合适，不自动调词库、不自动拉黑、不提升候选人证据。

## 私有数据与迁移

默认数据库 .jobagent/jobagent.sqlite3；Muse 可传自己的私有持久路径，同一用户使用同一账本。迁移17追加 roots/events/requests/sends 四表，事件只追加，事务与版本比较避免并发覆盖。跟踪表保存正文摘要与来源引用，不存已发全文；原获批全文仍在已有私有批次/会话事件中。回读输入、本人原话和消息证据也只放私有文件，引用须能在私有日志回查。

升级前备份私有数据库并停旧任务，执行新版本迁移；运行指纹改变时重新建立/显式迁移运行，不能绕过旧会话指纹验证。回滚政策用旧词库摘要；回滚数据库用升级前备份，不让旧代码读取新 schema。此版仅合成链路验证，真实 Muse 网页、账号认证、调度和两轮归因验收仍需宿主实测。
