# 用通用 computer use 做 JD 寻源：可行性、设计与缺口

日期：2026-10-24。状态：设计稿，**未实现**。本人要求：寻源由 agent 完成；不依赖 Claude in Chrome（避免绑定单一厂商），改用通用 computer use 采集。

## 结论先行

- **可行，而且仓库的入库边界已经是厂商中立的。** `worker ingest`（`WorkerFetchRequest` → `SourceJobRecord`）和 `jobs import-observations` 只认 JSON，不关心是谁、用什么工具采回来的。缺的是“执行器”这一层，以及“从剪贴板文本生成 SourceJobRecord”的确定性提取。
- **computer use 走的是操作系统级的键鼠输入，不经过调试协议（CDP）。** 本人截图已经证明：同一个 Chrome 里，手动操作的标签页一切正常，只有经调试协议发起的导航会卡住。键鼠输入和人手操作走的是同一条路径。
- **现成的厂商 computer use 工具在浏览器上都受限，这是宿主自己的安全策略，不绕过：**

| 宿主工具 | 现状 | 能否当执行器 |
|---|---|---|
| Claude 桌面 computer use | 浏览器只给“只读”权限，点击和输入会被拒（`docs/evals-design.md:211` 亦有记录） | 否 |
| Codex Windows Computer Use | 读取 Chrome 状态时报“无法可靠确认当前浏览器 URL”并终止（`docs/browser-control-diagnosis-2026-10-20.md` 第 4 项） | 目前不能；需维护方修复或新版本验证 |
| Gemini Computer Use 参考实现 | 通常经 Playwright 驱动浏览器，本质仍是调试协议 | 与现有问题同源，不选 |
| **自建执行循环**（任意视觉模型 + 本机截屏 + 系统键鼠 + 剪贴板） | 厂商中立；需要仓库自己提供全部护栏 | **推荐**，需本人确认 |

## 架构

```text
寻源计划（仓库，确定性）
  jobs search-plan / sourcing-budget / 来源清单 host_browser
        │  CollectionTask（站、检索词、城市、页数上限、间隔、额度）
        ▼
执行器（仓库之外的独立包，厂商中立）
  截屏 → 视觉模型给出下一步动作 → 本机键鼠执行
  取文本一律走剪贴板：Ctrl+L/Ctrl+C 取地址，Ctrl+A/Ctrl+C 取整页文字
        │  原始页面文字 + 地址 + 时间（不含截图、Cookie、令牌）
        ▼
确定性提取（仓库，可测试）
  按清单 jd_headings / stop_headings 截取 JD（复用 connectors/extraction.py 的 extract_bounded）
  地址校验 detail_url_prefixes，停止标志检查
        │  SourceJobRecord
        ▼
worker ingest（已有）→ triage → 外联审批（已有）
```

分层约束（AGENTS.md）：执行器**不进入** `src/jobagent` 的领域模块。建议放在独立目录（例如 `tools/desktop_collector/`），只通过 `worker ingest` 的 JSON 和仓库交互。领域代码不 import 键鼠、截屏或模型 SDK。

### 视觉模型只负责“点哪里”，不负责“读什么”

- JD 原文**不经过 OCR 或模型转写**，只取剪贴板里的原始文字，再由仓库按标题截取。这样 `jd_raw` 与页面逐字一致，满足“不用摘要拼凑 JD”。
- 模型只回答这些问题：搜索框在哪、第 N 张职位卡片在哪、页面是否加载完成、是否出现停止标志。这些都能在执行前后用剪贴板文字和地址复核。

## BOSS 的一轮采集（执行器动作序列）

1. 前置检查：本机只有一个自动化控制方；BOSS 当天额度足够（`sourcing-budget`）；拿到本轮检索词（`search-plan`）。
2. Ctrl+T 新开标签 → Ctrl+L 输入清单里的 `search_url`（填入检索词和城市码）→ Enter。
3. 等待加载（固定上限，比如 15 秒）。Ctrl+L、Ctrl+C 读回地址：域名或路径命中停止标志（`passport/zp/security`、`安全验证` 等），就停掉本站本轮。
4. 点击列表区空白处，Ctrl+A、Ctrl+C 取整页文字，确认出现职位列表。读不到就记为 `PAGE_LOADING`，等一次再试；还不行就停站，不刷新、不重开。
5. 逐张卡片（每轮最多 10 个详情，且不超过额度）：
   1. 视觉模型给出卡片坐标并单击，右侧出现详情；
   2. 单击详情标题，在新标签打开 `/job_detail/…`；
   3. Ctrl+L、Ctrl+C 取地址并去掉 `?` 之后的部分；Ctrl+A、Ctrl+C 取整页文字；
   4. Ctrl+W 关闭这个详情标签，回到列表；
   5. 两次详情之间至少间隔清单的 `min_seconds_between_pages`。
6. 翻页最多到 `max_pages_per_session`。
7. 每个检索词结束后 `jobs search-log`；全部文字交给提取器生成 `SourceJobRecord`，再 `worker ingest`。
8. 关闭自己新开的标签，不动本人原有的标签。

## 护栏（自建执行器必须自带，因为不再有厂商护栏）

- [ ] **点击禁区**：点击前截屏，由模型标出目标元素的文字；文字命中“立即沟通”“继续聊”“投递”“发送”“同意”“拒绝”的点击一律拒绝。点击后核对地址变化是否符合预期（列表 → 详情）。
- [ ] **只在允许的域名上操作**：每一步动作前读回地址，只允许清单 `search_url` 与 `detail_url_prefixes` 的域名；其他域名（包括本人正在看的别的网站）立即停止。
- [ ] **停止标志**：路径类标志只匹配地址，文字类标志只匹配正文（避免上一份调查里智联页脚登录链接的误报）。命中即停止本站当天的采集，写入汇报。
- [ ] **不处理任何验证**：不输入账号、密码或验证码，不拖滑块。
- [ ] **节奏与额度不放宽**：沿用清单与 `sourcing-budget`；失败不加速重试。
- [ ] **本机独占**：采集期间需要占用前台窗口和键鼠。开始前确认本人不在用电脑（或者另开一个 Windows 用户会话或虚拟桌面）；本人一动鼠标就暂停（检测到非执行器的输入即中止）。
- [ ] **截图不出本机**：截图只传给本人选定的视觉模型，不落库、不进日志；落库的只有剪贴板文字和地址。
- [ ] **单一控制方**：执行前检查日常 Chrome 上没有 chrome-devtools auto-connect、ChatGPT 扩展或其他调试会话附着；有就拒绝开工（不要自动去断开别人的连接）。

## 需要新增或修改的地方

| # | 位置 | 内容 | 类型 |
|---|---|---|---|
| 1 | `src/jobagent/connectors/` | `clipboard_page_to_record(text, url, manifest)`：按 `jd_headings` 截取 JD、校验详情前缀与停止标志，输出 `SourceJobRecord` 或拒绝原因。先写测试（BOSS、猎聘、智联各一份真实结构的样例文字） | 新能力，需同步能力目录 |
| 2 | `src/jobagent/schemas/` | `CollectionTask`：站、检索词、城市、页数、间隔、详情上限。由 `search-plan` 与清单生成，执行器只读 | 新契约 |
| 3 | `skills/job-hunting/sources/boss.yaml` 等 | `host_browser` 增加执行器用的页面提示（列表区域、详情标题位置），继续作为数据，不写成代码 | 清单数据 |
| 4 | `tools/desktop_collector/`（仓库领域之外） | 截屏、键鼠、剪贴板、模型适配器（OpenAI / Gemini / Anthropic / 本地模型可替换）与上面的护栏 | 新执行器 |
| 5 | `references/browser-sourcing.md`、`patrol.md`、能力目录 | 主通道改为“通用 computer use 执行器”；删掉“Claude in Chrome 优先”；写明一个 Chrome 只能有一个控制方 | 文档 |
| 6 | `.jobagent/tools/antigravity-session/` 与 broker | 日常 Chrome 上停止 chrome-devtools auto-connect；chrome-devtools 只用于另一个 Chrome 实例或本地测试页 | 运维 |

## 风险与未知

- **视觉模型点错位置**：靠点击禁区和点击后的地址核对兜底；最坏情况是点到无关元素，不会触发发送。
- **BOSS 对键鼠输入的反应未验证**：截图只证明人手操作正常。第一次执行器实测仍要按停止条件处理，出现任何验证或卡死都停下，不做规避。
- **速度**：截屏加模型推理，每个详情大约 20–40 秒，加上清单要求的间隔，每站每轮 10 个详情约 5–8 分钟。
- **占用电脑**：执行期间本人不能同时使用同一个桌面；这是通用 computer use 的固有代价。

## 建议的推进顺序

1. [ ] 本人确认采用“自建执行循环”，以及视觉模型由谁提供（可替换）。
2. [ ] 先做第 1、2 项（提取器与任务契约），全部离线、可测试，不碰浏览器。
3. [ ] 停掉日常 Chrome 上的 chrome-devtools 常驻附着（第 6 项）。
4. [ ] 做执行器最小版本：只做“打开搜索页 → 取整页文字 → 打开 1 个详情 → 取文字 → 入库”，先跑智联，再跑 BOSS。
5. [ ] 加护栏与点击禁区后，再扩到完整一轮和巡检。

## 释放 CDP 与授权弹窗（问题二）的关系

授权弹窗有两个来源，释放 CDP 后两者的情况不同：

| 弹窗来源 | 触发条件 | 释放 CDP、改用键鼠执行器之后 |
|---|---|---|
| Chrome 的“允许远程调试” | 每建立一条新的 auto-connect 连接弹一次 | **不再出现**：执行器不连调试端口。在 `chrome://inspect/#remote-debugging` 关掉开关后，任何工具都连不上，也就不会再弹 |
| agent CLI 的工具授权（agy `request-review`、白名单按 MCP 名记录） | 模型调用不在白名单里的工具 | **不再出现**：执行器直接调用模型 API 拿“下一步动作”，不经过 agy/Gemini CLI 的工具授权层 |

前提是**不要混用**：

- 释放 CDP 之后，如果又因为某一站（比如智联）重新接回 chrome-devtools，每接一次 Chrome 就弹一次“允许”，问题二会原样回来。要么三站都走键鼠执行器，要么 chrome-devtools 只连另一个 Chrome 实例（测试用），不碰日常 Chrome。
- 不要用 Claude / Codex 自带的 computer use 当执行器：它们有各自按应用、按会话的授权，而且对浏览器本来就限权（见上文“结论先行”）。

授权并没有消失，而是变成**一次性的本人配置**：执行器读取一个由本人确认的配置文件（允许的站点与域名、点击禁区词、节奏和额度上限、使用哪个视觉模型），启动时校验它的摘要。配置不变就不再询问；配置一改，就要本人重新确认。发送招呼仍走 `outreach ask/approve` 与 `worker authorize-greeting`，和采集授权分开。

运行状态已对齐：Codex 的受控检查已经结束，没有待完成请求。本人当前选择“保留连接，只做离线核验”；尚未停止 broker 或切换执行器。未来若明确释放并不再接回 CDP，就不会由新执行器触发这条 CDP 授权链。


## Codex 离线设计复核（2026-10-24）

核对回执：[键鼠执行器设计核对](../candidate/private/codex-harness/runs/TRI25_20261023/desktop-executor-design-review-20261024.txt)。本节不表示实现或三站实测已完成。

- 两类特定弹窗的触发链可以随旧CDP/CLI路径停用而移除；本地配置仍不能覆盖操作系统、浏览器、站点和模型API的既有安全要求。
- 远程视觉API会收到截图。“不出本机”仅适用于本地视觉模型；远程方案应承诺批准的接收方与不进入Codex/数据库/常规日志。
- 视觉禁区与事后URL检查不能保证“最坏不会发送”；护栏须先于首次真实点击，逐条发送审批保留。
- 剪贴板需验证新鲜度与窗口/页面/职位绑定，提取歧义就拒绝；不能直接宣称复制文字天然逐字正确归属。
- 批准摘要需独立保护，执行模型不能同时修改配置与批准记录来自行扩大权限。
- 受控检查已结束。本人明确选择保留当前broker且只离线核验，未停止进程、未关闭调试开关、未启动替代执行器。截图不进入Codex的边界保持。
