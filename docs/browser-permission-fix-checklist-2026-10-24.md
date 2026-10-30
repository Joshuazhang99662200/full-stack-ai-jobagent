# 浏览器调用与授权弹窗：问题点清单与解法

日期：2026-10-24。状态：本地脚本的可复现错误已离线修复，回执和复核见文末[执行回执与复核](#执行回执与复核2026-10-24)。真实浏览器路由仍封存，没有进行真实 Chrome 验收，**不能视为空白页问题已修复**。全局授权配置未改动。本文是执行清单，每一项都标明代码源头和验收方法。

> 更正：P1-1“站点在附着后重置页面”原先写成主因，但依据的 `dedicated-real-pages-state.json` 是模型归纳的结果，缺少 Target 生命周期与导航事件，只能算**待证假设**，不能当作结论。

## 结论先行

| 问题 | 主因 | 能否在本仓库修 | 解法方向 |
|---|---|---|---|
| 一：只有智联能直接读，BOSS/猎聘自动开页或跳成 about:blank | ① 待证：站点可能在调试连接附着后把页面重置为 about:blank；② 本地 wrapper 与提示词互相矛盾，把“新建页”“跳转”“同源校验”都拒成 PAGE_NOT_READY；③ agy 自带浏览器用的是未登录的独立 profile | ① 不能，也不该绕；②③ 能 | 按站分路由：智联走 chrome-devtools MCP；BOSS/猎聘不挂调试连接，回到既有巡检通道、官方 CLI 或人工补 JD；本地矛盾规则统一 |
| 二：反复弹出“允许 Gemini 调用浏览器”，不点就断 | ① agy `toolPermission=request-review` 且白名单只覆盖 `chrome_devtools_tri25/*`；② 实际运行目录不在 `trustedWorkspaces`，项目授权被清空、MCP 配置不加载；③ Chrome `--auto-connect` 每条新连接都要本人点“允许”，而驱动脚本反复新建连接 | ①② 能；③ 只能降低次数，不能取消 | 一次性统一配置：固定 MCP 名、补齐只读工具白名单、显式 deny 自带浏览器、固定工作区；浏览器连接只由一个常驻 broker 持有 |

---

## 问题一：BOSS/猎聘打开后变空白页，智联正常

### 证据

- `.jobagent/tools/antigravity-session/tri25-results/dedicated-real-pages-state.json`：BOSS `Navigation command reported success ... but Chrome target immediately reset/reverted to about:blank`；猎聘 `remained at about:blank with empty root web area`。导航**报告成功**，然后才变空白，所以不是本地拒绝导航。
- `tri25-results/browser-existing-tabs-diagnosis-v2.json`：附着的 Chrome 里只有智联、ChatGPT 等标签，**没有任何 BOSS/猎聘标签**，只有 blank/newtab 页。
- `tri25-results/TRUSTED_01EA8655_INTERACTIVE-BLANK_IDS.json`：现存 about:blank 页 6 个（ID 1、4、8、9、10、11），BOSS/猎聘页 0 个。
- `antigravity-session/logs/mcp_lifecycle_timeline.jsonl` 统计：`new_page` 被本地拒 27 次、`navigate_page` 被拒 22 次、`take_snapshot` 命中空白 16 次。
- `candidate/private/codex-harness/runs/TRI25_20261023/about-blank-log-root-cause-20261024.txt`：new_page 请求 13 次，其中 2 次 `Navigation timeout of 10000 ms exceeded`，失败后没有回收。

### 问题点与代码源头

- [ ] **P1-1 站点在附着后重置页面（主因，待最后核实）**
  - 现象：导航报成功后被重置为 about:blank，只发生在 BOSS、猎聘；智联（`kind: public_page`，服务端渲染）不发生。
  - 源头：站点页面脚本，不在本机代码里。来源清单的门控声明见 `skills/job-hunting/sources/boss.yaml`（`gate: security_verification_redirect`）和 `liepin.yaml`（`stop_markers`）。
  - 判定：这是站点的控制信号。按 AGENTS.md 硬性边界，**不写任何隐藏调试连接、伪装指纹、拦截跳转或改页面脚本的代码**。
  - 核实方法（只观察、不绕）：本人手动打开 BOSS，不开任何调试连接，确认页面正常；然后只做一次 `list_pages` + `take_snapshot`，看是否变空白。结果写进诊断记录，不重复测试。

- [ ] **P1-2 BOSS/猎聘根本没有可复用的标签，规则又禁止新建**
  - `scripts/mcp_devtools_wrapper.mjs:47`：启动参数 `--existing-pages-only`。
  - `scripts/page_readiness.mjs:27`：existingPagesOnly 下 `new_page` 一律拒绝。
  - `candidate/private/.../TRI25_20261023/persistent-browser-config.json`：broker 启动 wrapper 时带了 `--existing-pages-only`。
  - `resume_trusted_chrome.py:92`：“no existing tab → TARGET_NOT_FOUND; Never call new_page”。
  - 结果：BOSS/猎聘没有已开标签时只能失败，模型就去拿 about:blank 页凑数（见 P1-4）。

- [ ] **P1-3 几份规则互相矛盾，模型在矛盾里打转**
  - `TRI25_20261023/current-execution-entry.txt`：“缺少某站标签时，可用该站来源清单中的真实职位 URL 新建一次标签”。
  - `antigravity-session/.agents/agents/tri25-fetch/agent.md:16`：“本轮只复用已有页，不调用 new_page”。
  - `agent.md:24` 和 `interactive_worker.py:79`：又允许“协调器指定的 about:blank pageId 导航一次”。
  - `TRI25_20261023/run_live_collection.py:113`：“If no usable tab exists, new_page {url}”。
  - wrapper 的 `--existing-pages-only` 又把 new_page 全拒掉。四处说法不一致。

- [ ] **P1-4 复用空白页 + 同源校验，把跳转误判为空白**
  - `scripts/page_readiness.mjs:50`：导航时把期望 origin 记成请求 URL 的 origin。
  - `scripts/page_readiness.mjs:93-95`：快照的根 URL 与期望 origin 不同即 `PAGE_NOT_READY: blank, missing-body or wrong-origin`。
  - 风险：猎聘会在 `www.liepin.com`、`c.liepin.com`（简历）和 `safe.liepin.com`（验证）之间跳转；BOSS 门控会 302 到 `passport/zp/security`。这时把**真实的验证页**报成“空白/错源”，停止信号被吞，日志里看不出是被验证拦了还是空白。
  - 修法：origin 不一致时，先拿快照正文去匹配来源清单的 `stop_markers`，命中就如实报 `USER_INTERVENTION_REQUIRED` 并停站；不命中才报 `WRONG_ORIGIN`。不放宽同源校验本身。

- [ ] **P1-5 new_page 的空白初始页与导航超时不回收**
  - 上游 `chrome-devtools-mcp@1.11.0`：`tools/pages.js` L119-124 先 `Target.createTarget(about:blank)` 再 `goto`，超时 10 秒，失败没有回收分支（记录见 `about-blank-log-root-cause-20261024.txt` 第 4 节）。
  - 结果：跨轮次累积 about:blank 页（P1-2 证据中的 6 个），下一轮的 `list_pages` 里全是空白候选。
  - 修法：本地 wrapper 记录“本次会话创建的 pageId”；导航失败只关闭自己创建的页，不碰本人原有标签。

- [ ] **P1-6 模型退回 agy 自带浏览器（未登录 profile）**
  - `first-job-{boss,liepin,zhaopin}-untrusted-workspace-attempt.json`：`init_tools` 里有 `open_browser_url`、`read_browser_page`、`browser_*`、`execute_browser_javascript`，并且 `has_dedicated_mcp: false`。
  - 自带浏览器用的是 `~/.gemini/antigravity-browser-profile`，另有 `antigravity-session/chrome-execution-profile`。这两个 profile 都没有登录 BOSS/猎聘，智联公开页不需要登录，所以“只有智联能用”。
  - 修法：见 P2-3，用 deny 规则把自带浏览器工具关掉，只留 `chrome_devtools_tri25`。

- [ ] **P1-7 历史上的另一条故障链（不要混在一起）**
  - Codex 内置浏览器路由失效与 ChatGPT 扩展的 `unsupported_protocol`：见 `docs/browser-control-diagnosis-2026-10-20.md` 和 `.jobagent/diagnostics/browser-control-20261022.md`。这是宿主侧缺陷，与本文 P1-1～P1-6 不同因，不在这里修。

- [ ] **P1-8 仓库内（src/jobagent）不是原因，但缺一条停止原因**
  - `src/jobagent/connectors/observations.py`（`check_observation`）只校验宿主交回的 JSON：来源、URL 前缀、JD 长度、门控页。仓库没有浏览器执行器（`bridge/mcp_server.py` 只读账本）。
  - 可选改进：观察被拒原因里加一项 `blank_after_navigation`，让巡检汇报把“被重置成空白”与“没 JD”区分开。属于新行为，按 AGENTS.md 先写测试再改，并同步能力目录。

### 问题一的解法：按站分路由

| 站点 | 读取通道 | 说明 |
|---|---|---|
| 智联 | Gemini/agy + `chrome_devtools_tri25`（本人日常 Chrome，auto-connect） | 已验证可用（`tri25-results/live-zhaopin-01..04.json`） |
| 猎聘 | `jobagent jobs listings --source liepin`（官方 liepin-cli 只读搜索）→ `jobs fetch-jd`（公开详情）→ 门控时 `jobs ingest-jd` 人工补 JD | 不挂调试连接 |
| BOSS | 既有巡检通道（本人 Chrome，主会话读取，记忆里的“巡检走本机 Chrome”）；读不到就 `jobs add-jd` 人工贴 JD | 被重置为空白、出现验证页，一律按停止条件交人，当天不再试 |

- [ ] 在 `skills/job-hunting/references/browser-sourcing.md` 写明上表，并注明“附着后被重置为空白”是停止信号，不是网络故障。
- [ ] 统一 P1-3 的四处规则为一句：**有本人已开标签就复用；没有就返回 TARGET_NOT_FOUND，交本人打开；不新建、不复用 about:blank。**（如果要保留“用清单 URL 新建一次”，就要同时去掉 wrapper 的 `--existing-pages-only` 并实现 P1-5 的回收，二选一，不能并存。）
- [ ] 按 P1-4 改 `page_readiness.mjs`：origin 不一致时先匹配停止标志。
- [ ] 清理现存的 6 个 about:blank 标签：本人手动关闭，或只关本会话创建的。

---

## 问题二：反复弹授权，不点就断

### 证据

- `~/.gemini/antigravity-cli/cli.log`：`permissions=&{Allow:[mcp(chrome_devtools_tri25/...) ×9] Deny:[] Ask:[]}, toolPermission=request-review`，并且 `ApplyProjectPermissionGrants: no grants for project "CLI Project", cleared project permissions`。
- `~/.gemini/antigravity-cli/settings.json`：`trustedWorkspaces` 只有 `.jobagent/tools/antigravity-session`。
- `first-job-*-untrusted-workspace-attempt.json`：运行目录是 `candidate/private/codex-harness/runs/TRI25_20261023`；BOSS 第一次 `read_file` 之后、智联在 `write_file` 时都以 `CLI_PERMISSION_DENIED` 结束，猎聘 `TURN_TIMEOUT`。
- `~/.gemini/antigravity-cli/mcp/` 下有三套 MCP 名：`chrome_devtools`、`chrome_devtools_demo_20261023`、`chrome_devtools_tri25`。
- `.jobagent/tools/gemini-state/.gemini/settings.json`：只有登录方式，没有 `mcpServers`、`trust` 或 `tools.allowed`。

### 问题点与代码源头

- [ ] **P2-1 白名单只覆盖浏览器 MCP，内置工具每次都要问**
  - 源头：`~/.gemini/antigravity-cli/settings.json` → `permissions.allow` 只有 9 条 `mcp(chrome_devtools_tri25/*)`。
  - 模型实际还调用了 `read_file`、`view_file`、`write_file`、`call_mcp_tool`（见 attempt 文件的 `tool_steps`），这些都不在白名单里。`request-review` 模式下每次都问，无人值守时直接 `PERMISSION_DENIED`，表现为断点。

- [ ] **P2-2 运行目录不受信任，项目授权和 MCP 配置都不生效**
  - 源头：`trustedWorkspaces` 只有 `antigravity-session`，但 `run_live_collection.py`、`resume_trusted_chrome.py`、`interactive_worker.py` 把 agy 的 cwd 设成 `TRI25_20261023` 运行目录。
  - MCP 配置放在 `antigravity-session/.agents/mcp_config.json`，从别的目录启动就不会加载（attempt 里 `has_dedicated_mcp: false`），模型只能用自带浏览器（P1-6），自带浏览器的工具又不在白名单里，于是又要问。

- [ ] **P2-3 MCP 名称漂移，授权按名字记，换名就失效**
  - 源头：`.jobagent/tools/antigravity-session/demo-added-permissions.json`（`chrome_devtools_demo_20261023`）、`requested-permissions.json`（`chrome_devtools_tri25`），加上 `~/.gemini/antigravity-cli/mcp/chrome_devtools`。
  - 每换一个服务名，9 条授权就要重新点一遍。

- [ ] **P2-4 Chrome 自己的“允许远程调试”确认（不能取消，只能少触发）**
  - 源头：`persistent-browser-config.json` 中 `--auto-connect --channel=stable --user-data-dir=<日常 Chrome>`。auto-connect 的**每条新连接**都要本人在 Chrome 里点允许，这是 Chrome 的安全设计，不能也不该绕过。
  - 触发次数多的原因：
    - `mcp_connection_broker.mjs:58-60`：后端关闭即 `shutdown`，不自动重启；下次启动就是一条新连接，又弹一次。
    - `mcp_connection_broker.mjs:83`：已有客户端或请求未完成时报 `BROKER_BUSY`，驱动脚本误以为断线，转而另起连接。
    - 生命周期日志里出现过十几个不同的宿主 PID（`about-blank-log-root-cause` 第 2 节），说明有脚本绕过 broker 直接起 chrome-devtools-mcp。
  - `scripts/connection_wait.mjs:10-18` 把上游超时从 60 秒改到 300 秒，并改写 `getContext` 的竞速逻辑。这只是给人留出点“允许”的时间，治标不治本；它对 `chrome-devtools-mcp@1.11.0` 的源码字符串做替换，上游一升级就会抛错。

- [ ] **P2-5 有两套 CLI、两套配置**
  - `start-gemini.ps1`：gemini-cli 0.65，`GEMINI_CLI_HOME=.jobagent/tools/gemini-state`，配置里没有任何 MCP 或信任设置，用它跑每个工具都要问。
  - `start-antigravity.ps1`：agy，`$env:LOCALAPPDATA\agy\bin\agy.exe`，配置在 `~/.gemini/antigravity-cli/`。
  - attempt 文件里的 agy 路径是 `...\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\agy\bin\agy.exe`，即在 Codex 沙箱里被重定向的另一份安装；而驱动脚本写死的是 `<USERPROFILE>\AppData\Local\agy\bin\agy.exe`。两份可执行文件可能读不同的状态目录，授权不共享（**待核实**：对比两边实际读取的 settings 路径）。

- [ ] **P2-6 提示词声明的工具与实际需要的工具不一致**
  - `agent.md:4-5` 声明 `tools: [view_file]`、`commandExecutionPolicy: off`，但驱动让它做的事需要 `read_file`；`run_live_collection.py:90` 又要求 `write_to_file` 写预检标记文件。声明之外的调用一律要问或被拒。

### 问题二的解法：一次性收敛配置（由本人确认后执行）

修改授权配置属于安全设置，需要本人逐项确认，不由智能体自行改动。

- [ ] **固定一个 MCP 名**：只保留 `chrome_devtools_tri25`；从 `~/.gemini/antigravity-cli/mcp/` 移除 `chrome_devtools` 和 `chrome_devtools_demo_20261023`，`demo-added-permissions.json` 归档。
- [ ] **固定工作区**：所有驱动脚本的 agy cwd 统一为 `.jobagent/tools/antigravity-session`，结果文件用绝对路径交回；或者把 `TRI25_20261023` 加进 `trustedWorkspaces`。两者选一，不要两边都放。
- [ ] **补齐只读白名单，显式 deny 不该用的工具**（示意，字段以 agy 实际 schema 为准）：
  ```json
  {
    "permissions": {
      "allow": [
        "mcp(chrome_devtools_tri25/list_pages)",
        "mcp(chrome_devtools_tri25/select_page)",
        "mcp(chrome_devtools_tri25/take_snapshot)",
        "mcp(chrome_devtools_tri25/navigate_page)",
        "mcp(chrome_devtools_tri25/click)",
        "mcp(chrome_devtools_tri25/fill)",
        "view_file", "read_file"
      ],
      "deny": [
        "open_browser_url", "read_browser_page", "list_browser_pages",
        "browser_*", "execute_browser_javascript", "capture_browser_screenshot",
        "run_command", "browser_subagent"
      ]
    }
  }
  ```
  deny 掉的工具不会弹窗，也就不会退回未登录的自带浏览器（同时解决 P1-6）。`click`/`fill` 本人已永久授权，保持现状；发送招呼仍须经过 `worker authorize-greeting` 的一次性授权，与工具授权是两层，不能合并。
- [ ] **只保留一种 CLI**：用 agy 就停用 `start-gemini.ps1`；若要继续用 gemini-cli，在 `gemini-state/.gemini/settings.json` 里配置 `mcpServers.chrome_devtools_tri25`，用 `includeTools` 限定 9 个工具并设 `trust: true`。不用 `--yolo`。
- [ ] **驱动脚本只用一个 agy 路径**：`AGY_EXECUTABLE` 与 `start-antigravity.ps1` 对齐，并确认沙箱内外读的是同一份 settings（P2-5）。
- [ ] **浏览器连接只由一个常驻 broker 持有**：每天开工时 `start_connection_owner.py` 启动一次（Chrome 弹一次“允许”），所有驱动只走 `mcp_broker_client.mjs`，禁止直接 spawn chrome-devtools-mcp。broker 后端断了就报告并停下，由本人重新启动，不自动重连（自动重连会再次弹窗，也不符合“不自动重放浏览器操作”）。
- [ ] **处理 `BROKER_BUSY`**：驱动收到后等待上一请求结束或明确结束上一个客户端，不另起连接。
- [ ] **提示词与声明对齐**：`agent.md` 的 `tools` 写全实际要用的工具；预检不再要求写文件（`run_live_collection.py:90`），改为直接返回文本。
- [ ] **`connection_wait.mjs` 去留**：broker 常驻后保留 300 秒等待即可；同时锁定 `chrome-devtools-mcp` 版本（`package.json` 已是 `1.11.0`），升级前先跑 `test_connection_wait.mjs`。

---

## 推荐执行顺序

1. [ ] 本人确认上述配置改动范围（P2 解法第 1～5 项）。
2. [ ] 备份 `~/.gemini/antigravity-cli/settings.json` 与 `mcp/` 目录，再改。
3. [ ] 统一四处浏览器规则（P1-3），并改 `page_readiness.mjs` 的错源判定（P1-4）；先在 `test_page_readiness.mjs` 里写失败用例：“猎聘跳到 safe.liepin.com 应报 USER_INTERVENTION_REQUIRED，而不是 PAGE_NOT_READY”。
4. [ ] 启动一次 broker → 本人在 Chrome 点一次“允许” → 只读验收：智联一页 `list_pages` + `take_snapshot`，确认全程无 agy 弹窗。
5. [ ] 按 P1-1 的核实方法观察一次 BOSS；确认是站点重置后，把 BOSS/猎聘改走分路由表中的通道，并更新 `browser-sourcing.md`。
6. [ ] 跑全套门禁 `python -m pytest -q`（只有动了 `src/` 或技能文档时需要）。

## 验收标准

- [ ] 一次完整的智联采集轮次中，agy 侧授权弹窗为 0，Chrome “允许”最多 1 次（broker 启动时）。
- [ ] 日志里不再出现 `CLI_PERMISSION_DENIED`、`has_dedicated_mcp: false`，也没有调用 `open_browser_url` 等自带浏览器工具。
- [ ] 每轮结束后，新增的 about:blank 标签为 0。
- [ ] BOSS/猎聘出现空白重置或验证页时，汇报写明“停止：站点重置/验证”，而不是“空白页、技术失败”，当天不再重试。

## 明确不做

- 不隐藏或伪装调试连接，不改 `navigator`/指纹，不拦截站点跳转，不注入脚本对抗站点检测。
- 不关闭 Chrome 的远程调试确认，不改 Chrome 安全策略，不复制或读取登录 profile、Cookie。
- 不用 `--yolo`，不给 shell 或写文件开全局放行。
- 不把工具授权当成发送审批：首条招呼与回复仍走 `outreach ask/approve` 与 `worker authorize-greeting`。

---

## 执行回执与复核（2026-10-24）

执行方回执：《Claude清单：查询与调试回执（2026-10-24）》，原文见 `candidate/private/codex-harness/runs/TRI25_20261023/claude-checklist-debug-result-20261024.txt`。下表每一项都按本地文件复核过；“复核”一栏是本文作者实际看到的东西，不是转述回执。

### 逐项状态

| 项 | 执行方结论 | 复核 |
|---|---|---|
| P1-1 | 待证；没有把纯空白改报成站点封锁 | 同意。上文已更正，在受控对照完成前不作归因 |
| P1-2 / P1-3 | 统一以 `interactive_worker.py` 为唯一入口：复用非空白现有页，缺站返回 `TARGET_NOT_FOUND` | 已核实：`current-execution-entry.txt` 改为同一说法；`run_live_collection.py:2-3` 和 `resume_trusted_chrome.py:2-3` 直接执行即抛 `ENTRY_RETIRED` |
| P1-4 | 先匹配来源停止标志，再区分 `WRONG_ORIGIN` 与 `PAGE_NOT_READY`；同源验证页也停；停止后的交互被拒 | 已核实：`page_readiness.mjs:31-32`（停止后的交互被拒）和 `:107-119`（判定顺序）。停止规则 `source-stop-rules.json` 由 `test_checklist_fixes.py` 与 `SourceRegistry` 逐项比对。**发现一个缺口，见下** |
| P1-5 | 采用 existing-pages-only 分支，不新增建页和回收 | 同意，与 P1-3 的二选一一致 |
| P1-6 | 内置浏览器工具仍可见，未全局 deny | 属实；仍是未完成项，靠提示词约束 |
| P1-7 / P1-8 | 未改宿主，未改领域契约 | 已核实：仓库 `git status` 与本轮开始时相同，`src/` 无新改动 |
| P2-1 / P2-6 | 模型直接返回 JSON，宿主负责保存；旧的写文件预检已停用 | 同意 |
| P2-2 | 当前驱动的 agy cwd 是已受信任的 `antigravity-session` | 同意，上文 P2-2 描述的是较早的尝试 |
| P2-3 | 全局还剩 3 个历史 MCP 名，未删除 | 属实；仍是未完成项 |
| P2-4 | 存在 held state 或暂停标记时，owner 启动器报 `CONNECTION_HELD` 并退出，不另起进程 | 已核实：`start_connection_owner.py:15-16` |
| P2-5 | 沙箱内两条 agy 路径解析到同一可执行文件 | 接受；沙箱外的配置路径仍未证明一致 |
| 诊断误报 | `has_dedicated_mcp` 能识别 TRI25；无法判定时记为 `null` | 未逐行复核，相关回归在 18 项私有测试内 |

### 复跑结果

- Node 回归：`node --test test_page_readiness.mjs test_persistent_connection.mjs test_connection_wait.mjs` → 23 passed，0 failed。
- 私有 Python 回归：`test_checklist_fixes.py`、`test_driver_permissions.py`、`test_interactive_worker.py` → 18 passed。
- 仓库门禁：`pytest` 839 passed（152.79 秒，`--basetemp=candidate/private/t-1024c`）；`ruff check src tests` 通过；`mypy` 132 个源文件无问题。
- 以上都使用本地 fixture 或模拟进程，没有访问真实 Chrome。

### 复核中发现的缺口

- [ ] **G-1 智联详情域名不受停止标志保护。** `page_readiness.mjs:107` 只按 `search_url` 的 origin 找来源规则，而 `zhaopin.yaml` 的 `detail_url_prefixes` 里还有 `https://jobs.zhaopin.com/`。绑定在 `jobs.zhaopin.com` 的页面找不到来源，停止标志不会检查：同源的“安全验证”文字会被当成可读页面放行，跳到 `passport.zhaopin.com` 也只会报 `WRONG_ORIGIN`，而不是 `USER_INTERVENTION_REQUIRED`。
  - 修法：`source-stop-rules.json` 增加 `detail_url_prefixes`（同样从 `SourceRegistry` 派生），查找改为“页面 origin 等于搜索页 origin，或命中任一详情前缀的 origin”。先在 `test_page_readiness.mjs` 写失败用例：“绑定在 `jobs.zhaopin.com` 的页面出现‘安全验证’，应报 `USER_INTERVENTION_REQUIRED`”。
- [ ] **G-2 历史汇总被测试覆盖。** `live-collection-driver.json` 已标为 `audit_valid: false`，原始汇总没有恢复。以后做归因只用 `live-fetch-receipts.json`、`persistent-browser-events.jsonl`、`mcp_lifecycle_timeline.jsonl`。今后的入口红测一律在临时目录里跑。

### 仍未完成

- [ ] 受控对照（P1-1）：只 `list_pages`，由 Gemini 选一个已存在的非空白目标读一次文本；禁止新建、导航、截图、发送。不为对照关闭本人的 Chrome，也不重启已获准的连接。
- [ ] P1-6 / P2-3 的全局配置收敛（deny 内置浏览器工具、清理历史 MCP 名），需要本人确认后再改。
- [ ] 采集计数：智联 25，BOSS 0，猎聘 0；真实路由恢复前不会增加。

### 空白页相关代码的去留

业务层（`src/jobagent`）没有任何创建、截图或处理 about:blank 的代码。空白页只来自上游 `chrome-devtools-mcp` 的 `new_page`（先建 about:blank 再跳转）和导航失败的残留。围绕它的“复用空白页”“空白页截图”“空白就新开页”都没有业务价值：产出永远是 fetch=0，还会多触发工具授权、累积标签。

- [x] 复用空白页的例外已删除：`agent.md:24` 与 `interactive_worker.py:79` 现在都写明“禁止选择、导航或复用空白页，协调器也不能例外放行”。
- [x] “没有可用页就 new_page”的入口已停用：`run_live_collection.py`（`ENTRY_RETIRED`）。
- [ ] **采集链路去掉截图工具。** 采集只读文字，Codex 也不读截图，`take_screenshot` 只会对着空白页白跑（日志里有 62 次截图在页面未就绪时被拒）。从 `.agents/mcp_config.json` 的 `enabledTools`、`mcp_connection_broker.mjs:11` 的 `allowed`、以及 agy 白名单里移除；`page_readiness.mjs` 里只为截图服务的前置判断随之删除。需要截图的场景另配一个会话，不和采集共用。
- [ ] 只保留一处空白判断：`take_snapshot` 结果为空白或无正文时报 `PAGE_NOT_READY` 并停止该目标。这是唯一有用的部分，它防止把空白页记成“已读取”；不再派生任何“空白就重开、空白就截图”的分支。


## 补充查证回执（Codex，2026-10-24）

完整文字回执：[继续查证回执](../candidate/private/codex-harness/runs/TRI25_20261023/claude-checklist-debug-followup-20261024.txt)。本节记录后续真实检查，原文中的历史推断不因此成为已证实事实。

- [x] G-1 已修复：来源识别同时覆盖搜索页与全部详情前缀的精确 origin；停止规则继续与 SourceRegistry 比对。
- [x] 修复普通登录链接误报：智联页脚“企业招聘”指向 passport 的链接曾被误认为页面验证跳转。URL 型停止标志现检查主页面 URL，提示文字仍独立检查；真实验证页仍停止。
- [x] 修正空白诊断：BOSS 第一次快照的主根 URL 正确、状态 busy、无正文，其下另有 about:blank 内嵌页。旧日志任一 RootWebArea 命中空白就置位，不能据此说主页面已空白。现区分主根空白、子根空白和 busy，客户端记录摘要无需重启 owner。
- [x] 原持久连接已实测复用：四次受控 Gemini 任务始终复用 broker36792/wrapper10404/MCP25888，后端启动总数仍为1。工具共12次：列页5、选页4、文字快照3，无新建、导航、关闭、点击、填入、截图或发送。
- [x] 智联修复后真实读取成功（CONTROLLED_B73BB552），前后标签列表相同；不是仅 fixture 或离线回放。
- [x] BOSS 当前停止条件已核实（CONTROLLED_9E3158B1）：14:38:29列页为职位地址，14:38:32选页响应中实际显示 `/web/passport/zp/security.html`。随后停站，未执行 verbose 快照，未重试。此为真实验证地址信号；调试附着是否造成跳转、历史空白是否均同因，仍未证实。
- [ ] BOSS 默认 AX 节点过滤是否导致正文缺失仍待证；本轮对照因先出现验证地址而未执行。该站需本人在日常 Chrome 处理验证后才可继续，不绕过验证。
- [x] 新回执字段已逐项对照原始 RPC：最后一次模型将页面列表 URL 称为 snapshot_root_url，但实际未调用快照；核对汇总已剔除该字段及未观测标题。模型回复不能替代工具事实。
- [x] 最终验证：Node30通过、私有Python18通过、仓库pytest839通过（196.01秒）、Ruff通过、mypy131源文件通过、git diff --check通过。

所有临时工作区配置均按原始字节恢复。正常采集路由仍封存、暂停标记保留；真实采集回执仍为智联25/BOSS0/猎聘0。未修改全局九项 Allow、未清理其他 MCP 注册、未修改 Claude 配置。截图未进入本轮诊断入口；没有将“只保留一处空白判断”的建议用于删除必要的空白入口拒绝规则。
