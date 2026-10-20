# Codex 接入

从 GitHub checkout 构建至用户 `.agents/skills/job-hunting`，或将同版本发布包里的完整 `job-hunting/` 解压到该处；项目级安装也可用工作区 `.agents/skills/`。不要只复制未构建的 SKILL.md。

自然语言“使用 job-hunting 帮我求职”或 `$job-hunting` 触发后，先走 [harness.md](../harness.md) 的只读探测与初始化。技能元数据被发现时不执行脚本，也不启动 Codex 进程。

Codex 承担请求 JSON 的生成和独立复核。通过当前宿主的提问工具把证据确认和逐份审批直接交给用户，问必须先于答；将实际人类答复中继到 `applications approve`，不能自行产生同意答复。没有交互工具时给出可审阅文件和可交互终端命令，等待用户处理。

若宿主提供浏览器工具，可按其接口显示状态与请用户接管；没有时要求用户在自己的浏览器直接登录。插件、CLI、浏览器的 read 与 write 能力分别确认，不从可读推断可发。

周期工作仅用当前 Codex 产品实际暴露的 automation 能力，并且只在用户明确要求后注册。无该能力时给出配置交接；不安装 OS 服务，不把当前聊天的等待调用当作定时器。调度的 prompt 写明只读发现、候选人和工作区、用户选择后再生成、仅新结果/失败/需用户操作时通知。

来源：[Codex skills](https://learn.chatgpt.com/docs/build-skills)、[非交互模式](https://learn.chatgpt.com/docs/non-interactive-mode)。这是宿主接入协议，不是特定版本 GUI 功能保证。
