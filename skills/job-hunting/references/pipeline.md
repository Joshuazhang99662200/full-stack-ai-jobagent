# 后段 Pipeline：按需恢复与飞轮

处理单岗位后段状态、静默核对、标准表单、累计诊断或已确认规则复核时加载本页。只读取当前候选人、当前阶段的私有输入；类型权威在 schemas/pipeline*.py。详细格式、通用迁移与真实验收模板见 [工程协议](../../../docs/pipeline-flywheel.md)。

## 状态与审批

pipeline_jobs 是后段当前态权威，pipeline_job_form 是标准表单。intake继续处理人工入队、身份、完整JD、因子化与起草/独立复核；已有outreach / applications / conversations继续处理逐项审批、租约、发送和回读。pipeline只记录已发生的真实结果，不授予发送权。

九态为 draft_pending、greeting_sent、greeting_read、initial_contact、resume_requested、resume_sent、interview_pending、interviewed、abandoned。按固定转移表推进，不能用角标跳阶段；实际回复、索要简历、邀约、已面试和关闭都需来源证据。abandoned不能复活；同岗新联系要新轮次、新本人请求、新批准和新发送证明。

## 交互与每轮恢复

1. 固定版本，读取本人私有库和检查点。pipeline list/form核对当前行与meta.version，pipeline history按需查证；缺身份先回 [人工加岗](manual-job-intake.md)，不造pipeline行。
2. 对已绑定intake的行，正文/特征/草稿变化后pipeline sync，输入仅event_id、pipeline_id、candidate_id、expected_version。它从真实已校验产物重读，缺全文保持partial；旧JD失效清派生但保留已发原文/审计。
3. pipeline transition记录准确from/to、当前版本和证据；pipeline observe记录no_reply、substantive_reply、suspected_reply、pause或resume。实际新消息先走conversations inbound，消息原文仅在私有会话中保存。
4. pipeline due只给本轮核对清单。唯一静默时钟为真实sent/read/最后实质回复/定制简历发送中较晚时间加48小时；先读已加载对话再报no_reply。proof_pending、未知精确时间、暂停及终态不能凭空超时；interviewed不能no_reply自动关闭。
5. 登录跳转或匹配目标的回读不一致需暂停、交本人。host page-observe按站与messages/search分别记录；未加载只建议一次重载，不能报无回复。通知送达由宿主实际执行，恢复需本人原话。
6. 轮末host round-report / round-show保存搜索、pipeline、版本、页面与unfinished；下一轮用真实检查点恢复。旧tracking在该候选人pipeline authority启用后只读，不再写另一套当前态。

薪资原文、上下限、验证结果分别保留；比较固定upper_bound，底线和币种来自私有条件，未知或不可比REVIEW。扩展读取预算是显式宿主档，仍遵守来源URL、会话、间隔和风控；发送许可独立。

## 迁移与补证

pipeline inspect → 私有PipelineMigrationConfig → 停写备份 → migrate → verify-migration → project → 回读对账。expected_count、原ID序列、状态声明、字段映射、推导时间与证据、优先级全部由私有配置提供；公开核心没有任何个人批次默认值。缺URL继续留intake，摘要不入jd_text。历史发送声明可为greeting_sent/proof_pending，但sent_*为NULL；原批准/审计/准确回读齐全后pipeline bind-send。

旧host与新pipeline迁移均通过host backfill-plan/backfill-attach传真实migration_id；同名优先旧来源，错候选拒绝。plan只读完整清单与私有优先/未知ID；identity_unverified条目先确认身份。对已确认条目，用真实URL/provider恢复intake；attach校验原行和实际intake身份，通过原全文/预算门禁，再同步pipeline并追加旧SHA/v0到真实完整快照及观察时间的谱系。人工query_hit保持NULL；不自动发送。中断后原样重放同一事件续接，完成后只返回原结果；修改输入、废止轮次或错岗拒绝。原文件SHA与原ID/URL/title/company必须对应。只有迁移后无新事实且备份摘要一致才允许pipeline rollback；已有新观察、批准或规则时保留事实并交人处理，不能覆盖恢复旧文件。真实切换与任务恢复由本人另行授权，仓库不执行。

## 累计诊断与规则

先pipeline metrics保存原metric IDs，再diagnose；metric-show/diagnosis-show回读持久证据。七维scope必须来自来源，NULL为未知而非通配符；CONTENT_仅内容版本，不能当可比较harness。窗口闭合UTC [start,end)，比率为历史累计、当前切片累计、已确认规则生效后累计；window_rate仅展示。零分母为NULL；废止仍在分母，不重复相加累计窗口，也不跨联系轮次借转化。

诊断比较累计比率与历史×0.8，并核对相邻累计窗口持续性、伴随漏斗和排除原因；不设绝对样本数门槛。来源不足或边界抖动就持续观察。已读段阻塞不直接归因正文；简历段异常需确认招呼语段正常。

pipeline rule-propose绑定准确诊断、scope、前后规则和证据；rule-confirm必须本人看过完整效果后传原样rule_hash及原话引用。生成前confirmed-rules只按本候选人和适用scope加载。rule-review只追加有效/无效复核；无效时生成待确认回滚提案，不自行撤回。普通文案diff的成熟度门禁见 [回填与差异](muse-backfill-and-diff.md)，不替代累计比率诊断。未确认假设不得进入生成规则、词库或查询。

本协议没有改写Muse任务、读取真实招聘网页、发送招聘消息、创建任务或送达通知。真实迁移及两轮宿主验收均需实际回执，real_browser_verified=false保持不变。

## 新轮次回复绑定

同岗重联先由本人明确要求建立后续联系轮次；首招去重继续生效。原 conversation 中按原规则起草、出问题并逐条批准 `FOLLOW_UP` 或 `ANSWER` 后，用 `pipeline bind-reply` 的私有 `PipelineBindReplyInput` 绑定 `event_id/candidate_id/pipeline_id/expected_version/conversation_id/approval_event_id`。仅绑定本轮入库之后的真实 ask/approval，读取准确正文和版本，不新增审批、不发送。原会话关闭/拒绝、缺问题、上下文或附件变化时拒绝。

宿主照常通过原 `reply-gate` 执行及 `record-reply` 记录真实结果，再用原 `pipeline transition` 提供绑定会话、成功结果 ID 和准确回读推进 `greeting_sent`。缺全文继续 partial；原结果证明发送时间。回读不一致暂停原状态，不重发。同步不会用旧首招覆盖回复；待发送 JD 来源变化则清除回复绑定并暂停，重新交本人确认。详细字段及边界见 [工程接口](../../../docs/pipeline-flywheel.md)。