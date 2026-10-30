# Muse 与本地 Codex 通信：复用调查与接入建议

调查日期：2026-10-25。阶段：源码调查与待审设计，尚未安装 Muse 客户端、登录账号或验证真实往返。

架构更新：本人补充飞书 CLI 已承接通知、审批与状态回填，整体职责与事件流以 [事件任务架构](muse-codex-event-architecture-2026-10-25.md) 为准。本报告保留上游复用调查与通信完整性分析。

本人已选择：**本地 Codex 主控，双向回执**。首期目标是通信与完整结构化结果；JD 采集在通信验收后接入。

## 调查结论

GitHub 已有明显相似的双向桥接项目，可以复用协议处理思路和客户端进程边界，无须重写 Muse 网关协议。但本次检查的候选中，没有可以直接在当前 Windows 环境使用、又满足 JobAgent 完整契约回执的现成方案。

推荐组合：`nikships/muse-cli` 作为候选传输客户端，以 `buzhidaosm/muse-cli-bridge` 的任务中继作为参考，本仓库增加小范围的通信适配器，复用既有 Worker 入库和幂等回执。

## GitHub 候选与源码证据

| 项目 | 已核对的能力 | 与本任务的差距 | 复用判断 |
|---|---|---|---|
| [nikships/muse-cli](https://github.com/nikships/muse-cli) | Python CLI；send、history、侧边会话、事件订阅；MIT | 没有 JobAgent 任务契约；等待回复不按业务 task_id 精确关联；Windows 真实兼容性尚未验证 | 优先评估为独立客户端，通过子进程适配 |
| [buzhidaosm/muse-cli-bridge](https://github.com/buzhidaosm/muse-cli-bridge) | Muse 任务 JSON→本地 Codex/Claude→原会话结果；SQLite 去重、游标、投递状态；MIT | macOS 专用；方向以 Muse 派单为主；结果是有限长度 answer，无 JD 完整契约 | 最相似案例；参考中继协议与失败处理，不能原样移植执行器 |
| [supercheng1987/muse-local-agent](https://github.com/supercheng1987/muse-local-agent) | Windows PowerShell HTTP 执行服务，通过 ngrok 接入；返回 exit_code/stdout/stderr/truncated | 通用命令入口；需要入站隧道；没有业务任务关联、持久幂等或 JobAgent 校验 | 不作为首期实现基础 |
| [tegarp00/muse-ai-local-bridge](https://github.com/tegarp00/muse-ai-local-bridge) | 项目范围、精确命令白名单、文件分页、HTTP 工具；MIT | 需要隧道；主要解决项目工具访问，没有 JobAgent 完整回执 | 备用方案，参考白名单与分页 |
| [DaBinBinah/muse-bridge](https://github.com/DaBinBinah/muse-bridge) | 将 Muse 包装为兼容对话 API，文档提供 Codex 配置 | README 明确说明 Codex agent 工具调用依赖 function calling，当前以对话为主 | 不满足当前本机执行链路，排除为主方案 |

以上来自 README 与下列源码的静态检查。项目宣称的真实账号测试属于上游自述，本机尚未复现。

### 最相似项目的具体限制

检查 [TASK_BRIDGE.md](https://github.com/buzhidaosm/muse-cli-bridge/blob/main/TASK_BRIDGE.md)、[executor.py](https://github.com/buzhidaosm/muse-cli-bridge/blob/main/src/musebridge/executor.py)、[relay.py](https://github.com/buzhidaosm/muse-cli-bridge/blob/main/src/musebridge/relay.py)、[login.py](https://github.com/buzhidaosm/muse-cli-bridge/blob/main/src/musebridge/login.py) 与 [pyproject.toml](https://github.com/buzhidaosm/muse-cli-bridge/blob/main/pyproject.toml)：

- 包版本为 0.3.0，Python 3.11+，分类明确为 macOS。
- 登录固定查找 `/Applications/Google Chrome.app/...`；凭据使用 macOS Keychain。
- 中继导入 `fcntl`；执行器使用 `/usr/bin/sandbox-exec`、`os.killpg` 和 Unix 绝对路径判断。
- Codex 内层使用 `danger-full-access`，写入边界依赖外层 Seatbelt。不能移除外层后在 Windows 直接照搬。
- `scrub()` 将最终 answer 截为 20,000 字符；stdout/stderr 合计超过 2 MiB 会报错。没有最终 JSON Schema 约束。
- 结果只有 status、agent、mode、elapsed_seconds、answer；没有 SourceJobRecord、完整性摘要或 JobAgent 入库回执。
- 其去重按 task_id 主键忽略重复，未比较同号请求内容；本仓库 Worker 已有同号不同摘要拒绝规则，应沿用后者。
- 值得参考的是：发送前持久登记 unknown，含糊投递不自动再发；重启不重跑 running 任务；历史窗口缺口显式停止。

### Muse CLI 不等于完整回执

检查 [cli.py](https://github.com/nikships/muse-cli/blob/main/src/muse_cli/cli.py)：

- `cmd_send` 的 `sent: true` 可与“超时未收到回复”的 note 同时出现，不能作为业务成功。
- 回复选择依赖会话、事件 seq 和 `is_reply()`，没有应用层 request_digest/task_id 的精确匹配；必须另外绑定。
- `is_reply()` 只检查 status 非空，没有验证其具体值为 completed；适配层应明确判别终态。
- `_print_watch_row()` 会把显示字段截到 300 字符，watch 输出只能做进度提示，不能作为完整 JD 数据源。
- 完整原始事件应通过未裁剪的 history/raw 路径核对；其分页与长正文行为仍须在本机验证。
- 首次认证需要本人完成 Muse 登录；不应把凭据放进本仓库或结果回执。第三方协议的可用性不能视为官方稳定承诺。

## 本仓库已有的可复用接口

工作树已有多项未提交修改，其中包含 Worker 和 Codex 适配。此次只读取，未覆盖、提交或重构这些文件。

- `src/jobagent/schemas/common.py`：统一版本与 `extra=forbid` 契约。
- `src/jobagent/schemas/job_intelligence.py::SourceJobRecord`：岗位观察的唯一字段权威。
- `src/jobagent/schemas/worker.py`：WorkerFetchRequest、WorkerFetchReceipt、WorkerEvent。
- `src/jobagent/bridge/worker.py::WorkerGateway.ingest`：校验来源，原子写职位/回执/事件，相同任务幂等、不同摘要拒绝。
- `src/jobagent/cli/worker.py`：`worker ingest/show/events/ack` 是现有接入入口。
- `src/jobagent/bridge/codex_runner.py`：已使用本机 `codex exec --json --output-schema --output-last-message`，解析事件、检查最终契约和 request_id。

现有 CodexTextRunner 是文字协调器，明确禁用 shell、浏览器和插件。保留这个职责；本机 CLI 执行由独立、受控的宿主适配器负责。现有 mailbox 面向 Cowork/Claude 信箱，不能只改会话名就当作已经支持 Muse。

## 推荐通信设计（待确认后实施）

```text
本地 Codex / 宿主调度器
  → 本地通信适配器（任务账本、关联、完整性检查）
  → Muse CLI（本机主动建立出站连接）
  → 指定 Muse 侧边会话 / 采集任务
  → 未裁剪结果 / 分块 JSON
  → 本地契约校验与受控 jobagent CLI
  → Worker 入库回执与完整字段回读
  → 回传 Muse，并按任务号核对对端确认
```

这个通信拓扑不需要公网入站端口。若将来使用 Muse 主动回调本机的 HTTP/MCP 工具，则是另一个需要认证与访问控制的网络方案。

Muse 云端浏览器不自动拥有本机 Chrome 登录态。通信验收与浏览器能力验收分开；接本机浏览器时复用明确获准的宿主入口，不能从建立聊天连接推断本机 browser control 已接通。

### 请求、数据与回执

新增通信类型放在 `src/jobagent/schemas/`；嵌套使用现有岗位/Worker 类型，不复制模型。以下是拟议字段，不表示当前已有命令或能力：

| 层次 | 拟议内容 |
|---|---|
| 路由 | schema_version、task_id、request_digest、session_id、message_id、sender、recipient |
| 请求 | operation、typed payload、deadline；首期只允许 ping、echo、fetch_result 和本地结果确认 |
| 数据 | 原始 JSON bytes 的 SHA-256、字节长度、分块索引和数量；传输限制内直接载荷，超限时完整重组后校验 |
| 本机执行结果 | 受控操作标识、exit_code、stdout/stderr 的私有产物引用、完整性摘要、started_at/completed_at |
| 业务结果 | WorkerFetchReceipt，以及按 job_id 回读的完整岗位对象；不能只回 stored 条目摘要 |
| 确认 | ack_for、result_digest、接收端校验状态，任务与摘要必须匹配 |
| 异常 | timeout、interrupted、unknown、rejected、USER_INTERVENTION_REQUIRED；均不冒充 completed |

“完整字段”同时要求完整传输和完整业务读取：SourceJobRecord 的 source、source_job_id、title、company、location、salary_text、jd_raw、recruiter、url、job_kind、published_at、collected_at、search_term 及其 schema_version 均按原契约处理；可空字段显式保留 null，不编造值。

WorkerFetchReceipt 的 report 是存储摘要，不能代表 JD 正文已回传。接入后需同时验证原始观察与入库后 NormalizedJob 的全文和 provenance，允许归一化产生有契约依据的字段变化。

对长文本不做静默截断。分块必须可在所选 Muse 会话稳定读出；缺块、长度/摘要不符或无法分页读取均返回不完整状态，不能据此入库或报告成功。首期合成往返需验证后再确定载荷上限。

### 任务生命周期

区分请求已入本地账本、网关已受理、Muse 已接单、采集已完成、本地校验已通过、数据库已提交、对端已确认。各阶段各有证据，单个 sent/exit 0 不推动整条链路成功。

本地串行处理一个专用会话。按 task_id 与 request_digest 去重；同号不同内容拒绝。持久保存游标和待处理事件，重启从已确认位置恢复；执行/发送处于 unknown 时先查历史和本地回执，不自动重发或重跑。

云端文本不能直接成为 PowerShell 命令。新增适配器只映射已声明操作到固定 argv，以 `shell=False` 调用既有 CLI。首期只含通信与岗位读取/导入，不接投递、外发消息、证据确认或审批命令。对 Muse 的协议消息属于这次明确要求的双向通信范围。

## 可选路线

1. **推荐：Muse CLI 进程适配 + 现有 Worker。** Windows 改动最集中，保留当前 Codex 推理和 JobAgent 链路；代价是需补任务协议、游标持久化与完整回执验收。
2. **移植 muse-cli-bridge。** 可借鉴其现成队列与投递流程，但需替换凭据、锁、后台进程与沙箱实现，并改变主控方向、增加结构化结果；改动更大。
3. **本机 HTTP/MCP + 隧道。** 可让 Muse 直接调用本机工具，新增认证和入口管理成本；当前第一阶段没有必要引入。

若需要长期 Codex 会话和实时审批事件，后续可评估官方 [App Server](https://developers.openai.com/codex/app-server)；单次任务沿用 [非交互执行](https://developers.openai.com/codex/noninteractive)。本机 help 已确认 exec 的 JSON/Schema 参数，未启动新的模型任务。

## 第一阶段验收顺序

1. 静态依赖与 Windows 兼容性验证；固定上游版本/commit，检查许可证和网络行为。引入依赖或源码前更新 `references/oss/source-manifest.yaml` 与 `docs/oss-review.md`，保留许可声明。
2. 本地假传输测试：精确任务关联、错会话、重复、摘要冲突、未完成文本、超时、重启、历史缺口。
3. 本人登录后的真实 ping/echo：Codex→Muse→本机校验→回执→Muse 确认；覆盖中文、换行、null、嵌套对象和超过 300/20,000 字符的合成载荷。任一上游长度限制都必须显式暴露。
4. 一条合成岗位通过隔离数据库 `worker ingest`，回读完整岗位与原始观察、验证任务/摘要/事件，不能使用真实生产库替代演练。
5. 通信通过后，再验收一条实际获准浏览器或公开页面的 JD fetch。登录、验证码、风控、限流或空白/错页均停止，不计入新增 JD。

第一阶段完成的证据是匹配任务的完整往返、摘要一致和隔离入库回读；上游 README、自述成功或单个进程退出码都不替代这些证据。

## 本次验证状态

- PATH 找到 `codex.exe`，版本 `0.163.0-alpha.11.1`；未在 PATH 找到 muse-cli 或 muse-bridge。
- 默认 `python -m pytest -q`：552 passed、287 errors；首个错误为 pytest 无法在沙箱默认临时目录建立编号目录，未由此推断业务回归。
- 使用仓库私有短路径重新执行全套基线：839 passed，169.82 秒；没有改动 pytest 配置或全局临时目录。
- Ruff 通过；mypy 检查 131 个源码文件通过；`git diff --check` 通过（已有文件有换行格式提示）。
- 未安装或执行上游代码，未读取凭据，未发起 Muse 真实账号调用，未操作招聘网站，未修改运行时代码或既有未提交改动。
