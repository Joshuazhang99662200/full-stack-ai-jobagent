# 可安装的求职 Harness

本协议把现有原子能力组合为可恢复的求职工作。推理由当前 Codex 或 Claude Code 承担，确定性校验由随包 Python runtime 承担。安装不等于启动；只在用户调用本技能时初始化。

## 首次调用

1. 阅读本文件与当前宿主说明：[Codex](hosts/codex.md) 或 [Claude Code](hosts/claude-code.md)。确认安装目录有 `manifest.json`、`runtime/src/jobagent/` 与 `scripts/bootstrap.py`。若只有源码 skill 子目录，按 README 从完整 GitHub checkout 构建安装包；不要临时重写领域逻辑。
2. 使用用户选定的独立、可写工作区。没有选定时只询问工作区和简历位置，检查依赖可并行进行。候选人文件、请求与状态留在该工作区的 `candidate/private/`、`candidate/variants/`、`.jobagent/`；安装代码保持只读。
3. 执行 `python <skill>/scripts/bootstrap.py --workspace <workspace> --check`。这是只读检查，不创建计划、不登录、不发送。完整性失败先修复安装；依赖缺失时明确列出，再通过 `--setup` 在该工作区建私有 venv。不得覆盖全局 Python 或宿主配置。Python 需 3.11+。
4. 后续文档中的 `jobagent <argv>` 都通过 `python <skill>/scripts/bootstrap.py --workspace <workspace> -- <argv>` 执行。不能依赖全局 `jobagent`、开发者的 skill 或当前仓库 cwd。每个路径保持独立 argv，避免拼接 shell 字符串。
5. 为当前会话产生随机 session ID，执行 `jobagent harness start CAND_<ID> codex|claude-code --session-id <session>`。保存返回的 RUN ID。启动不创建候选人事实，仍需走候选人导入、询问与显式确认。

## 推进与上下文

按入口路由逐份加载所需策略，先查能力目录。每一步检查结构化结果后再继续。推荐过程：候选人入库与确认 → 只读发现 → 人选职位 → 补完整 JD → 定向草稿 → 独立复核 → 变体与 diff → 外部渲染 → PDF 检查 → 逐份预览、提问与人工审批 → 支持的单份交付或人工提交 → 实际结果汇总。

- 工作流中的等待位置写入 `jobagent harness checkpoint <RUN> <phase> --session-id <session>`。`waiting_for_fact_confirmation`、`waiting_for_job_selection`、`waiting_for_review`、`waiting_for_approval`、`waiting_for_login`、`delivery_outcome_unknown` 对应明确的人工交接。
- 状态只是进度，不能提升证据、授予审批或证明已投递。`completed` 也不能替代平台回执。
- 产物保存后可加 `--artifact <file> --contract <schema-name>`，绑定相对路径与文件摘要。支持 CandidateDraft、JobRequirementProfile、BaseResumeDocument、TailoredDraft、ClaimReviewSet、ReasoningHandoffRequest、ResumeVariant、PdfCheckReport、ApplicationPackage。保存到独立文件，已绑定文件不要原位修改；修订需重新校验并显式 checkpoint。
- 定向上下文只含母版引用或 JD 词项命中的已确认证据；遗漏项写在请求里。算法是确定性词项检索，不是语义搜索。母版若引用全部证据，可能仍选中全部；需要缩小上下文时先制作有证据溯源的母版子集，不随意截断事实。
- `AGENT_HANDOFF_REQUIRED` 是推理交接；读取该请求，按 schema 写输出，继续结构化 `resume_argv`。在安装模式下去掉 argv 首个 `jobagent`，通过 bootstrap 传余下参数。请求各有独立目录，不能借另一个请求的输出拼接继续。
- 定向改写默认 `optimizer tailor` → `optimizer review` → `optimizer assemble --review ... --request ...`。缺失、过期、拒绝或覆盖不全的独立复核都会阻断。单独复核步骤只读草稿与证据，逐条判断，不能复制生成时的自评。复核并不保证模型永不误判，保留用户最后评审。

## 恢复与交接

开始任何恢复先 `jobagent harness status <RUN>`，核对候选人、等待原因与产物。然后 `harness resume <RUN> <host> --session-id <session>` 校验产物并获取租约。租约默认 30 分钟，checkpoint 可续期。有效租约不能被其他会话抢占。

当前宿主退出或交给另一个宿主前 `harness release <RUN> --session-id <session>`。另一个宿主需能访问同一用户工作区，随后 resume。不要共享浏览器 cookies、密码或会话秘密。凭证能力仍由新宿主独立探测。

到期租约仅能显式 `resume --recover`。先确认旧会话停止，再恢复，不能据此重发未知结果的申请。若崩溃留下 `state.lock`，先确认没有任何写进程，在用户工作区手动移除该运行的锁文件，再 resume；不能自动删除仍有所有者的锁。终态运行不能重新打开，另建 RUN。

## PDF、登录和计划

运行还绑定代码与技能策略的 `runtime_digest`。版本改变时拒绝恢复，即使使用 `--recover` 也不能跳过；使用匹配发布包或人工评审后另建运行，不自动迁移旧审批与状态。

默认尝试已安装的 resume-builder；没有时交接模板与待渲染的验证变体，明确 PDF 尚未生成。不要把它写作编译成功。渲染后执行 `jobagent harness check-pdf <variant.json> <resume.pdf> --max-pages 1|2`，再看实际版面。严格文字门禁只允许变体条目、原样 section 标题与条目前的列表符号（•▸▪·◦）。姓名、联系方式、求职意向不是经历主张，经 `--header <header.json>`（`{"lines": [...]}`）提供，只能原样出现在第一条目之前，报告记录其 `header_digest`。“公司｜职位｜时间”等分段行必须作为引用任职证据的变体条目进入复核，不能由渲染器自行补写。

文本门禁不能证明字体、美观、视觉遮挡或 PDF 的主动内容安全；输出依赖渲染器和人工版面检查。附件与可编辑源文件均保存在用户工作区。准备投递前再核对 PDF 摘要与 PdfCheckReport；当前 ApplicationPackage 不含附件字段，已注册猎聘投递器因此停止交人。用户手动提交也必须在完整投递包的具体审批后进行，不能把岗位选择视为发送同意。

浏览器、凭证存储、计划任务和通知是宿主能力。能力未确认存在时保持 `host_probe_required`，不宣称具备。缺安全凭证输入时用户在网站直接登录；不索取聊天中的密码或验证码。登录、验证码、风控、限流均停下，请人接管后显式恢复。

只有用户明确要求周期检查才注册宿主原生调度，保存时区、工作区、候选人和只读范围。无新岗位、失败或待处理事项时保持安静。调度只发现岗位，不审批、不投递、不发招聘方消息。当前会话循环退出即止；本地机器关闭不能声称仍在运行。无法访问本地数据的云宿主不能默认接替。

## 准确汇报

逐个 ApplicationPackage checkpoint 后执行 `jobagent harness report <RUN>`。报告只含 ID、审计结果与次数；无审计为 unknown，mock 成功为 simulated，人工接管不计 sent。演练 `applications send --dry-run` 不写审计，不计投递。人工在网站完成的提交没有本项目回执，直到取得实际回执前仍汇报为外部待确认。

消息草稿由宿主按 message-generation 策略起草并提交用户评审，目前没有独立消息生成服务。发送招聘方消息属于独立对外操作，需明确授权，不能从安装、寻找职位或审批简历推断出任意联系权限。
