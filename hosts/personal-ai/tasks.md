# 宿主定时与交互任务协议

定时由Muse等宿主提供。公开仓库不创建本机计划任务、守护进程、隧道或推送桥。本人首次设置定时能力时指定频率、时区、时段、每轮上限和通知方式，并保存真实任务ID/下一次运行。后续直接加载；只有本人明确要求才调整。没有设置就保留手动单轮，不默认全天运行，也不在每轮重复追问。版本升级与私有数据库切换分别验收。

## 动态参数与能力核对

首次配置前用 `rules prepare` 的 `initial_setup` 生成表单；本人逐项确认必需值后登记 `rules initialize`。若已有初始化记录，直接复用，不重开表单。首次真实 JD 验收也须先完成配置与预算核对。

后续每轮先读 `rules effective` 并以 `ordinary_run` 准备只读计划，核对候选人、当前版本与 pending_changes，不重复询问或要求确认。任务类型切换、会话恢复、缺项、歧义、过期或冲突都不触发配置交互；相关步骤暂停并说明，保留已有值。只有本人明确发起调整，才以真实 owner_request 进入 `owner_requested_change`。支持的执行入口显式传当前 `--rules-file`。改后首轮展示变量旧值、新值与版本，真实通知成功并回读后才 acknowledge。暂停窗口按 `rules evaluate poll` 求值；求值不创建宿主任务。

`rules evaluate abandonment/ratio` 只产生候选结果与提案，默认通过 `--database` 核对权威当前 head；历史回放必须显式 `--historical` 并保留历史标签。pipeline 的生产写入在事务内核对当前放弃策略和比例消费者；缺值或不兼容即 `not_integrated`，相关状态、历史和派生诊断保持原样，不回退固定规则。详见 [动态变量](../../skills/job-hunting/references/dynamic-variables.md) 与 [pipeline](../../skills/job-hunting/references/pipeline.md)。

目标岗位、地区、薪资与排除项来自当前候选人的明确配置，适用于工程、研究、设计、金融、运营、销售等方向；岗位示例不构成默认意向。

## 搜索与人工加岗

> 读取固定代码版本、本人私有候选人/已确认证据/硬条件/基础查询/当前域词库和检查点。验证单实例锁，已有同轮任务则恢复，不另开。聊天URL、不可变列表编号、卡片都先intake enqueue；未知目标先selection/resolve，缺URL不建pipeline行。每次交互与轮询开始intake list，逐项next恢复，成功一步重读当前版本。完整JD、独立复核、草稿和兴趣学习分别推进；仅明确岗位兴趣记录like，文案Accept不推断喜欢岗位，也不授予发送权。
>
> 每站先sourcing-budget，再用sourcing-start和当前rules-file固定已确认的查询、每查询取数、轮次详情和日额度；本轮计划不重新征询数字。intake strategy后claim真实计划，每次网页动作前reserve，allowed=true才读取，再记真实结果。预算档显式选择且须兼容确认值，不自动增额或降回旧默认。查询观察以sourcing-take回显requested、实际观察、不足与平台ID重复；关联同一来源与run，详情失败/取消/重复仍占轮次与日额度，不能切换入口、ID、库或账号增额。保留来源URL、会话页数、间隔、本人限额和风控停止。预算触顶如实记录未遍历完及恢复点。成功query才record-search，new_count必须真实明确；计划、失败和登录页不记成功。人工/推荐来源不伪造query_hit。
>
> 完整原文按真实时间/身份/预算绑定snapshot后才能factorize和起草。缺正文保持partial，不用要点拼全文。JD变化按原链路清失效派生；已绑定pipeline的产物变化同步并回读form，失败列unfinished。薪资比较显式upper_bound，阈值/币种来自私有条件；未知或不可比保留REVIEW。草稿展示来源、准确全文、证据和缺口；生成与独立复核分开执行。

具体入队与知识路由见 [人工加岗](../../skills/job-hunting/references/manual-job-intake.md)、[JD知识](../../skills/job-hunting/references/jd-knowledge.md) 和 [寻源预算](../../skills/job-hunting/references/sourcing-budget.md)。本任务不发送招聘消息、不投简历、不修改在线资料。

## 使用 MCP 时的实际调用

> 本轮确需 MCP 搜索/查看时，按 [MCP 实际调用](../../skills/job-hunting/references/mcp-runtime.md) 用当前确认快照与已有 sourcing_run_id 建立 MCP 轮次，支持的调用统一走 mcp batch。round-start、连接初始化及工具核验均不计业务调用、不预扣上一轮投递；实际 tools/call 派发才记账，同时占所属寻源轮次的查询或详情额度。缺 MCP_BATCHSIZE 等确认参数只阻塞，不把提议当本人决定，不重新追问。
>
> 批内受确认并发和批大小约束，批间串行；搜与查看共计调用。首次实际派发从权威已关闭前轮的正向回读投递事实派生扣额，报告起始额度、扣额、实际调用与剩余。成功搜索使用同一 TOP/不足/精确ID去重回执，详情失败和重复照常占轮次及日额度；工具成功不证明 JD 完整。429001、限流、风控、屏蔽或已投递信号停线，不换入口重试。
>
> 完成回放直接读取既有回执；unknown 先核验后 reconcile，保留原未知与消耗，核验不自动解除日停站。宿主不得绕过网关直接调用外部 MCP 来避开额度与停站；本地网关不能拦截宿主独立调用的工具。投递仅可登记逐项交接和本人授权后实际观察到的结果，不执行 raw apply，不替代原批准与附件门禁；当前猎聘无法传输获批定制附件时仍交人。

## 页面与后段核对

> 每站分别观察messages/search，host page-observe仅用logged_in/login_redirect/not_loaded三档。未加载最多建议一次重载，仍未加载保持未确认，不能当无回复；消息登录失效暂停同站后段，搜索失效不推断消息状态并记录实际sourcing gate。登录、验证码、限流或风控立即停止该站并通知本人，不受“无变化安静”偏好影响，不绕行、不换账号。程序返回通知要求不等于已送达，宿主须保存实际回执。
>
> 候选人pipeline authority已启用时，pipeline_jobs是后段当前态，旧tracking只读。pipeline list/form/due恢复每个联系轮次；兼容性检查通过后，due才给真实截止点与expiry_due，先读实际已加载对话再observe，不根据截止点列表凭空废止。时钟锚点只取实际sent/read/最后实质回复/定制简历发送中较晚时间；已确认时长、立即原因或简历阶段范围不受当前生产契约支持时，停止相关状态写入。proof_pending或无精确时间不超时，暂停不冒充无回复，interviewed不自动无回复关闭。
>
> 实际新消息先conversations inbound，再用真实来源时间/引用推进pipeline transition或substantive_reply观察；角标只记suspected_reply。索要简历、邀约、已面试、拒绝和岗位关闭分别要真实证据。回读不一致拒绝并暂停匹配目标，交本人核对，不重发。恢复须本人原话。abandoned为终态，新联系需要独立轮次、新本人请求、新批准与新发送证明。

详细证据和命令输入见 [pipeline](../../skills/job-hunting/references/pipeline.md)。当核心或持久文件能力缺失时停在可核验范围，不能搭建替代本地控制链。

## 获批动作单独触发

> 本人批准具体岗位、准确全文和实际定制附件后，才处理这一项。用同版本现有outreach / applications / conversations门禁复核摘要、目标、内容、附件、租约、节奏和查重；许可不满足就停止。宿主重新核对页面岗位/招聘方，准确使用获批内容，逐项执行并回读后写原审计。新正文、新附件重新批准。结果不明先核查会话和审计，不能重发；平台不支持获批附件时交人，不换入口规避。pipeline只绑定既有真实结果，不替代发送门禁。

## 累计飞轮与规则

> 按预先定义的闭合UTC窗口运行pipeline metrics，保留原metric ID和evidence，再diagnose。scope七维来自真实JD特征、版本和验证薪资；NULL表示未知，CONTENT_不是可比harness。历史/切片累计/优化后累计分别核算，单窗口仅参考；废止留分母，排除原因及原岗位引用保留。无来源、无基线、伴随段不齐或边界抖动时持续观察，不用绝对样本数强行诊断。
>
> 诊断只生成提案，pipeline rule-propose展示准确scope、前后规则和证据；本人逐条确认准确rule_hash及原话后才rule-confirm。生成前confirmed-rules按当前候选人及适用scope加载，不能把未确认假设当规则。下一闭合窗口按真实rule_id复核；rule-review无效只给回滚提案，实际撤回/恢复仍待本人确认，不自动改事实规则或投递权限。

普通文案diff另按 [回填与差异](../../skills/job-hunting/references/muse-backfill-and-diff.md) 处理，不能把它的观察成熟度阈值当后段比率诊断门槛。

## 轮末保存与恢复

> 零新增也保存真实报告。host round-template填本轮实际run/plan/claim、查询与读取、query_hit归因、去重/过滤证据、新入库/新稿、词库版本、pipeline各态/待补证/静默截止点/暂停/新废止原因、分站分页面状态和unfinished。未知为NULL，有证据的0才写0。round-report后round-show回读，保存检查点、任务版本、实际下轮时间与必要通知回执。两轮独立、顺序真实后verify-rounds；real_browser_verified=false保留，由本人核验宿主真实结果。

私有迁移与切换先按 [宿主接线](../../skills/job-hunting/references/muse-host-adoption.md) 和 [工程协议](../../docs/pipeline-flywheel.md) 完整对账；实际行数、原ID、待补证声明、带稿/缺身份项由私有配置列出。首轮不一致保持暂停，受保护回滚只在没有后续事实时允许，不能丢新数据库事实强行恢复旧JSONL。

## 宿主验收记录

逐项保存GitHub实际SHA、私有随机标记写入/重读、新会话恢复、本人证据确认、两站完整JD及真实来源、单实例锁/中断恢复、实际任务ID/时区/下次时间、只读状态核对和规则确认。合成演练审批摘要变化/重复事件/故障恢复；真实发送只留待本人批准具体一项后验证，不能为“接通验收”先发送。

本工程未改写运行中的Muse任务，未访问招聘网站，未发送消息或附件，未创建任务，未送达通知。真实迁移、数据库切换、连续两轮及通知恢复均为unverified，须宿主在本人授权后另行执行。
