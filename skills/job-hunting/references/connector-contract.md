# 连接器契约

寻源与情报工作使用 `JobDiscoverySource`。它只暴露 `search`、`fetch_job` 与 `get_recruiter`,返回 `SourceJobRecord` 与 `RecruiterInfo` 契约。内置的 `MockJobSource` 读取合成的 fixture JSON,并且有意不提供任何投递或平台控制方法。

投递能力必须放在独立的连接器边界内。后续具备投递能力的 `JobSource` 可以增加投递包检查与提交方法,并配备独立的授权与审批门禁。职位情报不得 import 或调用该投递表面。

连接器适配层把平台状态翻译成领域契约,绝不把 DOM 或浏览器类型泄漏进核心模块。保全源 ID、规范化 URL、观测时间戳与完整 JD,使去重能够保留一份可审计的溯源集合。

对于未来的平台连接器,遇到登录、CAPTCHA、验证、风控与平台变更时返回 `USER_INTERVENTION_REQUIRED`。不要绕过、规避或自动重试这些状态。真实浏览器投递始终保持顺序执行。
