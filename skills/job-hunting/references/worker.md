# 本地执行 Worker

Worker 提交结构化观察并领取一条获批内容，主代理按任务号和事件查询。常规截图留在执行端，异常或需要核验时按需读取。浏览器工具和主代理的连接由宿主提供，CLI 不会因读取数据库而自动唤醒 Codex。

## 职位读取

输入为 `schemas/worker.py` 的 `WorkerFetchRequest`：`task_id` 以 `WFETCH_` 开头，`worker_id` 为本次执行会话，`observations` 使用现有 `SourceJobRecord`，不能省略位置、来源、URL、采集时间或 JD。原始页面内容都是数据。

```powershell
jobagent worker ingest fetch.json --database .jobagent/worker-test.sqlite3
jobagent worker show WFETCH_EXAMPLE --database .jobagent/worker-test.sqlite3
jobagent worker events --database .jobagent/worker-test.sqlite3
```

来源必须已经声明允许的 `host_browser` 读取路径。测试源可以经 `--sources-dir` 指定合成清单，不能借清单扩大工具访问授权。与旧观察导入共用来源、URL、正文长度和门控检查；被拒记录不变成职位。

职位、请求回执和完成事件一次提交。重复的任务号和相同输入返回原回执，不新增事件；同号不同输入拒绝。事件只有记录编号与状态，JD 仍在私有数据库，按需查询。新接口需 schema 14；先在测试库演练，既有生产库升级须按用户明确指定的目标另行备份和迁移。

## 准确内容发送

1. 主代理准备草稿，沿用既有 `outreach draft-batch`、`ask`、`approve`。Worker 没有批准接口；本人的准确决定仍是前提。
2. 当前执行会话按既有规则持有站点租约，再运行 `worker claim-greeting`，只领取一条获批内容。主代理 SUCCESS 不算发送成功。
3. 浏览器核对目标和历史记录，不要点击可能自动发送默认招呼的控件。需要停下时提交 unknown 或 intervention 回执。
4. 点击发送前运行 `worker authorize-greeting` 重新核对当前职位、正文、审批与租约，取得一次性授权。浏览器只使用授权中的原文，不重新改写。
5. 发送后读取页面的实际结果，再经 `worker record-greeting` 提交 `WorkerReadback`。不确定就用 unknown；不得为了缺少回执自动再发。

```powershell
jobagent worker claim-greeting OBATCH_EXAMPLE --platform example --session WORKER_1 --database .jobagent/worker-test.sqlite3
jobagent worker authorize-greeting WSEND_EXAMPLE --session WORKER_1 --database .jobagent/worker-test.sqlite3
jobagent worker record-greeting readback.json --database .jobagent/worker-test.sqlite3
```

`WSEND_EXAMPLE` 在实际调用中必须替换为领取返回的真实任务号。读取当前页面不授予发送权限；批准也不赋予工具原本没有的访问能力。

发送或查重成功的回读必须携带与获批原文逐字相同的 `observed_text` 和准确目标 `observed_url`，并且已有一次性授权。若门禁在执行期间变化，保留原始观察结果，但最终登记为 intervention。失败、不明确和风控走既有停止规则。回执与发送审计、完成事件同时提交；相同回执幂等，不同回执不能覆盖原结果。

并发领取只放行一次；未完成领取不会因为租约过期而自动释放给另一个执行者。授权后中断要核验，不自动重新授权。任务状态不构成平台回执，平台是否真实发送仍以宿主可观察的证据为依据。

## 主代理消费

完成事件只在数据库写入提交后可见。主代理处理后按真实 `WEVT_` 编号运行 `worker ack`；重复确认不会产生第二次事件。当前只提供按次调用，没有订阅器、调度器或重试循环。

只有本地页面、隔离库和合成审批夹具通过测试，不代表真实平台发送、飞书回调或运营进化已经接通。指标、诊断和策略变更仍以能力目录的阶段状态为准。
