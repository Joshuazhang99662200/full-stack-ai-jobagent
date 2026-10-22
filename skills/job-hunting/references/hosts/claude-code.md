# Claude Code 接入

从 GitHub checkout 构建至用户 `~/.claude/skills/job-hunting`，或将同版本发布包里的完整目录解压到该处。项目级安装使用 `.claude/skills/job-hunting`。共享正文与 runtime 和 Codex 相同；不改用户全局 CLAUDE.md、MCP 或 hooks。

用 `/job-hunting` 或自然语言请求触发，随后执行 [harness.md](../harness.md)。Python 命令都经 bootstrap，不能假设已有全局 jobagent。自启动表示调用 skill 后自动推进已授权步骤；不会在安装后启动后台 Claude Code。

当前 Claude Code 作为推理引擎，完成请求指定 schema；独立复核使用单独推理步骤，并只加载复核请求的数据。任何事实提升与逐份投递审批都要求用户针对具体对象确认，不能借助 hooks 自动生成审批答复。

浏览器、MCP、原生电脑操作若未提供则手动交接。登录时用户直接操作网站，不在聊天里交出密码或验证码。云执行器需要另行具备候选人工作区访问条件，不能假定读取本机安装 skill、私密数据库或浏览器状态。

调度能力先按实际 CLI / Desktop / cloud 场景探测；会话内 `/loop` 不提供退出后的保证。只有用户要求才建原生计划，范围限于只读发现与通知，保存时区与工作区。缺原生能力时交配置，不自行安装后台服务。

来源：[Skills](https://code.claude.com/docs/en/skills)、[Hooks](https://code.claude.com/docs/en/hooks)、[计划任务](https://code.claude.com/docs/en/scheduled-tasks)。安装位置兼容已做自动化验证；真实 Claude Code 会话和调度需在用户环境验证。
