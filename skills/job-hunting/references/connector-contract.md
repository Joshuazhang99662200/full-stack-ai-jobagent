# 连接器契约

寻源与情报工作使用 `JobDiscoverySource`。它只暴露 `search`、`fetch_job` 与 `get_recruiter`,返回 `SourceJobRecord` 与 `RecruiterInfo` 契约。内置的 `MockJobSource` 读取合成的 fixture JSON,并且有意不提供任何投递或平台控制方法。

不是每个平台都提供 JD 正文。结果页只给摘要字段的来源实现 `JobListingSource`,只暴露 `search_listings`,返回 `JobListing`。listing 可以驱动发现与确定性硬过滤,但**永远不能冒充完整职位观测**:两个端口刻意分开,就是为了让「没有 JD」这件事在类型层面无法被绕过。绝不用摘要字段合成 `jd_raw`。

`LiepinCliJobSource` 是第一个真实来源:它把外部 `liepin-cli` 当作不透明进程边界,只调用只读的 `job search`,并实现 `JobListingSource`。该 CLI 的 `job apply` 与 `resume` 写入命令**不接入**,投递必须走独立边界,在线简历保持只读。token 过期、401/403、验证码与风控翻译为 `USER_INTERVENTION_REQUIRED`;退出码 2 在非交互环境下不打印任何提示,一律按需要人工授权处理。输出不是合法 JSON 或缺少契约必填字段时翻译为 `INVALID_PROVIDER_OUTPUT`。子进程输出可能是 GBK 而非 UTF-8,连接器自行解码。上游未声明许可证,因此除进程调用外不得复用其代码。

投递能力必须放在独立的连接器边界内。后续具备投递能力的 `JobSource` 可以增加投递包检查与提交方法,并配备独立的授权与审批门禁。职位情报不得 import 或调用该投递表面。

连接器适配层把平台状态翻译成领域契约,绝不把 DOM 或浏览器类型泄漏进核心模块。保全源 ID、规范化 URL、观测时间戳与完整 JD,使去重能够保留一份可审计的溯源集合。

对于未来的平台连接器,遇到登录、CAPTCHA、验证、风控与平台变更时返回 `USER_INTERVENTION_REQUIRED`。不要绕过、规避或自动重试这些状态。真实浏览器投递始终保持顺序执行。
