# 采集约束与恢复

适用于所有岗位方向。目标岗位、薪资、地区和来源读取候选人的明确配置；示例岗位不变成默认排除规则。

## 一次详情读取

1. 将真实目标页面、来源、唯一 attempt_id、`profile: "standard"` 和来源清单中的 `expected_daily_cap` 写入私有请求文件。
2. 执行 `jobs reserve-read <request.json> --database <私有库>`，检查 `allowed`。只有新预留的 true 才执行本次读取；false 是重放回执，先核验既有结果，不再次开页面。
3. 宿主在自己获准的工具与登录态中读取目标，随后执行 `jobs record-read <outcome.json> --database <私有库>`。实际失败也消耗尝试，不把失败改成零结果。验证码、登录、限流、风控和未知结果暂停相应来源，通知本人。
4. 观察中保存 `read_attempt_id`，其来源和页面须与成功读取一致。单一尝试只能绑定一个捕获版本。其他被拒绝或未入库的读取仍计入预算。

仓库不控制浏览器；这些命令是接入协议门禁。绕开此协议直接操作外部工具不属于已验证的执行链，不能宣称受到程序额度保护。来源上限最多 50，显式期望与实际不同就停止，不替换 profile。

## 原始观察和面板

观察字段见 `SourceJobRecord`。新采集必须声明 `completeness: "full"` 及 `access_state: "public"` 或 `"authenticated"`；遗漏保持 unknown，不入正式 JD 链路。面板另外提供 `capture_kind: "panel"`、实际面板页面 URL、`panel_locator`、`panel_source_job_id`，并核对平台岗位 ID。摘要、要点和哈希不能证明全文完整。

同一岗位的 JD 或薪资变化形成新观察，不能生成一次新的联系资格。原始正文逐字保存在追加历史；规范化正文可以折叠空白，但不替换原始证据。用 `jobs observation-history JOB_*` 查询版本元数据；正文只在私有库中。

## 整轮对账

用 `jobs check-coverage <report.json>` 核对 input_ids 与 dispositions。每条只有一个去向：draft_ready、needs_jd、rejected、duplicate、closed、unsupported 或 deferred，并写理由。完整采集还需可访问、已加载声明；预算、干预或中断退出要有 last_cursor。该检查不证明宿主实际翻过未提供的页面，运行报告必须说明真实覆盖范围。

消息列表的 CLI 快照需传 `--access-state authenticated --coverage full --load-state loaded`。加载中、受限、部分覆盖与真正的已加载空列表分开保留；受限/部分记录不能覆盖比较基线，未读数变化不推断新回复。

## 反馈与历史

下一次显式采集前按当前候选人和操作者消费反馈。策略内容相同，版本不变；父版本只记录谱系。持久化失败不能推进消费映射，采集因登录失败也不抹除已经提交的本人反馈。

历史未保存全文、缺精确发送时间或检查已错过时保留未知和时间精度，不用新采集的数据改写旧事实。库/队列切换必须先确认唯一可写权威并对账，不把公开增量迁移等同于个人私有系统已经迁完。
