# 公开职位补充渠道

国内招聘平台继续作为主要渠道。`public_careers` 只补充明确配置的企业 ATS board，当前代码支持 Greenhouse 和 Ashby 的单响应公开 API。没有内置本人来源清单；尚未对任何真实企业 board 做平台请求验收，合成测试通过不等于该企业可用。

## 配置与运行

配置文件由已有私有来源提供，包含 `boards`（每项为 `provider`、`board`、`company`）和当前候选人的 `filter_context`（既有 `CandidateFilterContext` 契约）。来源身份同时保存 channel、provider、board、平台岗位 ID 与原始 URL。URL 必须与企业 board 和岗位 ID 一致；不递归发现来源，不读取任意 URL。

`filter_context.allowed_locations` 必须来自本人已确认的地区条件。缺地区则阻塞此入口。远程、混合办公、未知地区保留待判断；“Remote”不会推断为可在中国履职。英文地区按词边界比较，不把 China 匹配到 Chinatown。中英文无法直接比较时保留待判断；需要的别名由本人现有地区配置显式列出，程序不自动翻译或改写本人值。确定不符合地区的岗位不进入候选列表，原始响应仍保留供覆盖核对。跨渠道仅可记录关联候选，不凭标题自动合并。新记录不创建或重开任何联系轮次、关闭或已拒绝状态。

命令使用现有已确认动态规则；缺新渠道预算时只报告缺项，不开启配置表单、不修改任何本人值。新变量均无默认，需走既有本人主动调整协议：

| 变量 | 单位与消费者 |
|---|---|
| `PUBLIC_CAREERS_HTTP_PER_DAY` | 次/候选人/上海业务日（Asia/Shanghai），所有公开 provider 和 board 共享 |
| `PUBLIC_CAREERS_HTTP_PER_ROUND` | 次/公开渠道轮次 |
| `PUBLIC_CAREERS_HTTP_PER_BOARD` | 次/来源board/候选人/上海业务日（Asia/Shanghai） |
| `PUBLIC_CAREERS_QUERY_PER_ROUND` | 次/轮，本期每个board实际请求为一次query |
| `PUBLIC_CAREERS_MAX_BYTES` | 字节/响应，拒绝压缩、超限停止 |
| `PUBLIC_CAREERS_TIMEOUT_SECONDS` | 秒/请求，包含DNS、连接、TLS与读取截止检查 |
| `TOP_PER_QUERY` | 条/查询，复用已有取用上限，只限制处理与入库数 |

一次 board API 可同时返回多份内嵌 JD。HTTP 请求次数、query 尝试次数、实际返回条数、观察条数、地区待选条数、取用条数与重复条数分别记录。内嵌 JD 属于列表观察，不伪造单独详情访问；本期 `detail_attempts` 为零，`fetch` 只读取当前已缓存观察。`TOP_PER_QUERY` 不限制已经收到的条数；下载边界由 bytes 限制负责。单独详情端点未实现，不宣称已接入浏览器详情预算。

```powershell
jobagent public-careers scan --candidate-id CAND_SYNTHETIC --config .jobagent/public-careers.json --rules-file .jobagent/rules.json --run-id explicit-round-id --database .jobagent/jobagent.sqlite3
jobagent public-careers list --candidate-id CAND_SYNTHETIC --database .jobagent/jobagent.sqlite3
jobagent public-careers status --candidate-id CAND_SYNTHETIC --database .jobagent/jobagent.sqlite3
```

以上是合成命令格式，不是本人配置。`scan` 开始前验证显式规则与预算，结果包含契约版本、规则版本及生效预算；每次派发的事务再次核对权威规则版本。`list`、`status` 不联网、不创建或迁移数据库，旧库或缺表返回错误。

## 安全与覆盖

统一 TLS 传输仅连接固定 API 主机和从严格 board 标识构造的路径。DNS 解析后检查全部地址，拒绝本机、私网、链路本地和元数据地址；直接连接已校验 IP，TLS 仍验证原主机名，避免二次解析。禁止重定向、环境代理与自动重试。单次命令串行派发，同一候选人有未完成请求回执时拒绝新的派发。

HTTP 记账在已连接、请求即将派发的持久 checkpoint 完成。DNS、TCP 或 TLS 失败保留失败轮次与错误，HTTP 计数为零，不冒充已派发请求。checkpoint 后崩溃保留结果未知，需核验，不自动重复。403/429/401/验证码/风控持久停 provider，后续轮次保持暂停；没有自动解除或重试命令。

原始响应按请求保存；每轮保存准确配置快照，每条原始输入按来源和数组下标保存 invalid/rejected/deferred/taken/duplicate 去向，能够与原始响应逐条核对。失败、格式错误、缺数组、业务失败指示与成功空数组分别处理。无 JD 只保存 listing，不升级为完整观察；完整 JD 经既有 `JobNormalizer` 和 `SqliteJobRepository.save_observation` 入库，历版观察保留。部分条目格式错误、缺 JD、取用触顶或响应声称后续分页均报告 `partial`。首期不自动续页，恢复信息说明需要缩小显式来源范围或由本人主动审阅取用设置，不能自动重读整个 board 冒充续页完成。

`boards_completed` 仅表示该 API 响应遍历完成；`resume_board`、错误及各类计数保留未完成范围。运行失败、暂停或取消不改变国内渠道或岗位业务状态。本能力不授予发消息、投递、审批或修改在线简历的权限。

## 来源与依赖

独立 Python adapter 参考移植 Career Ops 固定提交的 Greenhouse/Ashby 与网络防护经验，不调用上游 provider 或顶层 scan，没有新增 Node 或 pip 依赖。见 [OSS 评审](oss-review.md)与[来源记录](../skills/job-hunting/references/oss/career-ops.md)。
