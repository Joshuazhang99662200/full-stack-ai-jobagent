# Muse-only 旧桥接移除计划

本次只交付计划，未删除飞书、mailbox、MCP、dashboard 或 bridge。当前CLI承担核心校验与审批，不整包删除。是否停止兼容旧本地使用者仍需明确决定；先保留现有入口。

## 第一步：重新核对全仓调用

在实际待删版本运行以下只读搜索，保留本地输出，不把旧审计当作最新零引用证明：

~~~text
rg -n "feishu|feishu_push|lark-cli|bridge.status|bridge.mailbox|mcp_server|patrol_dashboard|mailbox inbox" src scripts tests skills hosts README.md pyproject.toml
rg -n "_rewrite|auto_push|notify_app|mailbox_app|_push" src tests
~~~

本次核查仍有13个文件命中旧链路关键词，不能直接以目录名删除。桥接拆除必须同时处理测试、命令注册、能力目录和文档。

## 第二步：迁出通用改写规则

src/jobagent/bridge/feishu_approval.py 的 _rewrite 保留了“编辑正文后重新展示、本人重新确认后才能登记审批”的通用语义。先将其迁入outreach领域服务或宿主卡片处理器，增加原文编辑/错摘要/旧审批失效/逐项重新确认的测试，确认Muse textbox也走此规则。禁止因删除飞书文件丢失此门禁。

## 第三步：按关注点删除

1. 删除飞书推送与卡片构建、notify子应用和注册，剥离outreach ask的auto_push及patrol finish的_push；保留ask/patrol主体。
2. 删除mailbox模块与子命令，更新技能上下文路由和能力目录。
3. 删除本机MCP中继、注册脚本和dashboard。确认status无剩余调用后才移除；bridge目录为空后才删除包。
4. 每批先跑相关bridge/CLI/outreach/patrol/能力目录测试，再跑CONTRIBUTING的四条全套门禁。每批单独提交；失败时回退该批，不覆盖其他新事实。

必须保留jobs/intake/快照/校验链、outreach审批与授权审计、storage/schemas、连接器工厂与extraction以及hosts/personal-ai契约。没有独立“事件层”模块可按名称删除；next/lease/record与repository仍是执行协议的一部分。

## 验收与mock边界

使用合成数据模拟“手工加岗→身份解析→真实格式完整JD输入→因子化/词库→草稿→本人确认→许可检查”，只核验核心状态，不实际发送。host迁移、page-observe和两轮报告可演练持久化；mock通过不能代替真实Muse网页、通知送达、定时恢复和已批准发送的回读验收。

## 每批门禁命令

第1批：python -m pytest -q tests/bridge tests/cli tests/outreach tests/patrol tests/test_capability_status.py；第2批追加全仓 rg -n "mailbox|mailbox_app" src scripts tests skills hosts；第3批追加 rg -n "mcp_server|register_jobagent_mcp|patrol_dashboard|bridge.status" src scripts tests skills hosts。测试目录以待删版本实际存在为准，先用 rg --files tests 核对，不让不存在路径掩盖漏跑。

每批都重新运行第一节两条全仓搜索，以及 python -m pytest -q、python -m ruff check .、python -m mypy src/jobagent、git diff --check。记录剩余引用的理由；不能只删除报错测试使门禁变绿。
