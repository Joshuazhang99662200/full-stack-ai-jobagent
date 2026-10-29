# 已发送消息的观察与历史归档

只在需要查看已发证据、只读观察或追溯旧记录时加载本页。当前pipeline状态的操作按pipeline协议；回复与附件仍按conversation.md、hitl-approval.md逐项审批。

## 当前状态权威

私有库中 pipeline_authorities 对候选人存在切换回执后，pipeline_jobs 是唯一当前流程状态。旧 tracking start / event 的写入会结构化拒绝并要求使用 pipeline；tracking due 返回空列表。tracking status / history / report 只读取保留的历史，不把旧 awaiting_reply 当作另一套当前状态。

切换按候选人隔离。尚未切换的候选人可继续使用旧跟踪接口，但活动规则也统一使用同一个48小时时钟。不存在按检查次数或旧多日节律废止的第二套政策。新pipeline出现后不能通过换旧命令重开已终止流程。

## 建档与证据边界

只有现有outreach人工审批、准确正文摘要、sent审计和宿主逐字回读一致，tracking start 才保存sent → awaiting_reply历史。也可引用既有conversation的reply_approved和实际sent reply_result。approved=true、发送意图和批次时间窗口不能替代原审计。

程序校验的是私有记录和回读的一致性，无法认证宿主浏览器或账号。sent_at来自原审计recorded_at，并保留sent_time_basis=audit_recorded_at；不能用迟登记时间伪装实际发送时间。回读不一致不建正式跟踪；已有记录发生异常时暂停，不重发。

~~~json
{
  "candidate_id": "CAND_DEMO",
  "tracking_id": "TRACK_DEMO",
  "audit_id": "OAUDIT_DEMO",
  "readback_text": "宿主实际读到的准确全文"
}
~~~

conversation来源改用conversation_id、reply_result_event_id，不能与audit_id混用。超出通常首查时段的迟登记需显式next_poll_at（未来的实际下一轮时间）。registered_at保留实际登记时间，check_count从0开始；missed_check_days仅兼容读取旧审计，不再根据已退休的节律推导新值。登记不补填观察，也不因没有检查次数延后已经到达的废止期限。

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

pending只投影既有批准与站点租约，不取得租约、不发送、不创建当前pipeline状态。实际对外动作继续原outreach next等门禁。

TrackingEventInput包含event_id、tracking_id、candidate_id、expected_version、kind、observed_at（含时区）、observation_id、evidence_reference、evidence_kind。同ID同文重放幂等，异文或过期版本拒绝。观察按时间追加，拒绝未来消息和旧发送轮次消息。

先通过conversations inbound保存真实对方消息；reply_confirmed、substantive_reply、初筛、邀约和拒绝从库核对同岗位/平台/会话/事件及实际received_at。asks_resume、interview_invite、declined必须来自该既有入站事件；宿主仍负责忠实分类，不把系统消息或自动摘要当实质回复。

read_confirmed只接受conversation_message/list_message和相同job_url的真实已读观察。它不增加检查次数，每次发送轮次只能首次确认一次，反复打开同一已读回执不能延长时钟。未读数、角标变化只能记suspected_reply，不确认已读或回复。

## 唯一48小时时钟

截止时间 = max(sent_at, read_at, last_substantive_at) + 48小时，空值不参与比较。没有确认已读时以实际发送或最近实质活动为准；确认已读后使用较晚的真实证据时间。实质回复以原消息received_at重置，迟到登记或反复观察旧消息不能把时间改成当前时刻。

旧接口默认每4小时生成只读检查机会，并在48小时截止时到期；宿主按实际轮询执行，不为凑次数反复打开页面。no_reply必须有真实加载的消息页观察，失败、重复、未加载和角标不增加有效检查数。check_count只是无上限审计计数，不触发或阻止废止。到截止时间的第一条真实无回复检查直接写no_reply_2d或read_no_reply_2d，再追加closed；不能因漏查而补造次数，也不能为了补次数继续等待。

真实reply_confirmed/substantive_reply/初筛等推进保留last_substantive_at并重排只读检查。新的reply_sent必须有新的绑定审批、实际发送结果和准确回读，才开启新发送轮次并重置已读/活动元数据。不会借此自动生成或发送跟进。

拒绝、同URL岗位关闭、本人明确放弃按现有证据门禁立即归档。closed不复活、不再到期检查。登录/风控/回读异常保持原状态并paused，清空到期；本人处理后明确resume，再读取实际对话，不能把登录页或未加载当无回复。

## 私有数据与审计

使用候选人自己的私有数据库，路径由宿主提供。旧roots/events/requests/sends保留不可变历史，版本比较和事务防止并发覆盖。状态历史保存摘要、来源引用和实际观察时间；已发全文留在既有私有批准批次或会话中，不进入公共仓库。

历史report的观察模式只供回查，不会改变搜索权重、自动拉黑或提升候选人证据。新飞轮诊断单独使用pipeline累计比率与本人规则确认，不能用旧模式报告替代。

升级前备份并停旧写者，验证私有迁移后才记录pipeline_authorities切换回执。公开代码测试不代表私有数据、实际网页、通知或调度已验收；这些由宿主逐项核验。
