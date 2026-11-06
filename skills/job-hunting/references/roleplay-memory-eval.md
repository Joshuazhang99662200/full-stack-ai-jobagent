# 记忆系统长程角色扮演验证

本页只在本人要求用角色扮演验证记忆系统时加载。全程使用合成人设、合成证据和合成岗位，工作区独立，**不发送任何消息，结果不能用于真实投递**。

## 分工

| 角色 | 谁 | 能看到什么 |
|---|---|---|
| 求职者本人 | 本机 Claude Code 会话（扮演合成人设） | `roleplay persona` 的人设与隐藏偏好；每轮的 JD 与招呼 |
| 起草、独立复核、记忆总结与选择 | 本机 Gemini CLI | 只有程序打包的 JD、已确认证据、记忆规则与本人反馈原话；**不含人设和隐藏偏好** |
| 裁判 | `roleplay report` | 六项不变式、隐藏偏好是否被记忆学到、前后半程通过率 |

Gemini 能学到偏好的唯一途径，就是本人每轮留下的决定、改写原文和理由。报告里某条隐藏偏好显示已捕获，说明这条链路是通的。

## 准备（只做一次）

1. 在本机克隆仓库、切到包含本功能的分支，`python -m pip install -e .`。
2. 确认本机装的是哪种 CLI，并已登录。两种都支持，由配置里的 `protocol` 区分：
   - **Gemini CLI（`gemini`）**：`echo "只回复 {\"ok\": true}" | gemini --output-format json`，输出里应有 `response` 和 `stats.tools.totalCalls`。
   - **Antigravity CLI（`agy`）**：`agy models` 应列出要用的模型。agy 的最终结果不报告工具调用次数，而且无人值守时读文件不经授权，所以必须用 stream-json，从过程事件里数工具调用。

   输出证明不了"没用工具"时，`roleplay round` 会失败关闭，不会重试。
3. 新建一个**空目录**作为工作区并进入，后续命令都在这里运行。写私有配置 `.jobagent/gemini.json`，二选一：

```json
{"argv": ["gemini", "--output-format", "json"], "timeout_seconds": 180}
```

```json
{
  "protocol": "agy_stream_json",
  "argv": ["<agy 可执行文件完整路径>", "-p=", "--input-format", "stream-json",
           "--output-format", "stream-json", "--model", "gemini-3.8-flash-high"],
  "timeout_seconds": 600
}
```

agy 每次调用实测要 1 到 3 分钟，一轮要调用多次；超时设到 300 秒时曾有一次调用超时，所以示例用上限 600 秒。超时也按失败处理，不重试。

Gemini CLI 指定模型时在 argv 里加 `"-m", "<模型名>"`；agy 用 `agy models` 里的模型编号。不要在配置里放密钥，也不要加 `--dangerously-skip-permissions`、`--yolo` 这类自动批准工具的参数，配置会直接拒绝。

两种 CLI 都可能读取用户级的全局上下文（如 `~/.gemini/GEMINI.md`）。里面若有写作或求职偏好，会和记忆规则一起影响 Gemini，测出来的就不只是记忆链路；运行前先确认，必要时在报告里注明。

4. `jobagent roleplay init --scenario evaluation_first_v1`，再 `jobagent roleplay persona` 读一遍人设。

## 每一轮

1. `jobagent roleplay round --gemini-config .jobagent/gemini.json`。输出含 JD、`greeting`、本轮所选规则 `selected_rule_texts`。`generation_status` 为 `rejected` 时说明 Gemini 的稿子没过独立复核，记下原因，直接进入下一轮。
2. 以人设身份判断，按隐藏偏好和常识只选一个动作：
   - `approve`：完全满足偏好；
   - `revise`：岗位可以但文字不行，`revised_text` 写本人改好的全文；
   - `decline`：岗位方向不要，`reason_category` 选 `direction`。
3. 写决定文件 `.jobagent/roleplay/decisions/R<轮次>.json`（目录不存在时先创建），再执行 `jobagent roleplay decide <轮次> <文件>`：

```json
{
  "action": "revise",
  "words": "改一下：先讲评测，别说很感兴趣。",
  "reason_category": "copy",
  "note": "开头先讲搭评测体系的经历，删掉客套话",
  "revised_text": "您好，我在知识库问答产品里搭过评测集……",
  "triggered_preferences": ["P_EVAL_FIRST", "P_NO_PLEASANTRIES"]
}
```

扮演规则：

- **`note` 每次都要写一句本人理由。** 没有理由的单次决定，程序不允许被总结成通用偏好，这是设计如此，不是故障。
- `triggered_preferences` 只填这次决定实际依据的隐藏偏好编号，供裁判核对，不会传给 Gemini。
- `words`、`note` 和改写文字里**不要照抄隐藏偏好原文**，要像真人一样用自己的话反馈。否则测出来的是抄写，不是学习。
- 不要编造人设证据之外的经历；改写只能使用已确认的合成证据。
- 不直接改数据库或记忆文件，所有动作只通过上述命令完成。

4. 每 5 轮运行一次 `jobagent roleplay report`。

## 长程运行

在本机 Claude Code 里可以用 `/loop` 让会话自己控制节奏，例如把下面整段作为循环提示：

```text
在当前目录继续 CareerHarness 记忆角色扮演验证，按 skills/job-hunting/references/roleplay-memory-eval.md 执行。
你扮演 `jobagent roleplay persona` 里的合成人设。每次唤醒完成一轮：round → 按人设判断 → 写决定文件 → decide。
每 5 轮跑一次 report，把不变式失败、新捕获的偏好和通过率变化追加到 .jobagent/roleplay/journal.md。
任一不变式失败、Gemini 连续 3 轮失败或生成被拒，或已完成 40 轮时，停止循环并汇报。
```

14 个合成岗位会循环出现，第二遍遇到同一 JD 时可以直接对比前后稿件。

## 怎么读报告

- `checks` 中任何一项为 false 都是记忆系统缺陷，优先排查，不要继续刷轮次。
- `preferences[].captured`：在对应类别的记忆规则里出现了关键词即判为捕获。关键词判定只是粗筛，最终以 `matching_rules` 原文是否真表达了该偏好为准。
- 触发过却始终未捕获的偏好，说明反馈没有被总结成规则，或总结得太保守，属于需要改进的地方。
- `first_half_acceptance` → `second_half_acceptance` 上升，说明记忆在起作用。样本小时只看方向，不作统计结论；要看统计意义，用 `memory simulate` 估计需要的轮数。
- `P_NO_SALES` 属于 jobs 类偏好，只影响后续找岗，不影响招呼。它被捕获，只说明回绝理由进入了记忆。
