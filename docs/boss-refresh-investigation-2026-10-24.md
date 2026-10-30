# BOSS 页面反复刷新：现象、证据与结构性缺口

日期：2026-10-24。范围：只读本地日志、驱动结果与脚本；没有操作浏览器，没有访问 BOSS，没有读取 Cookie 或截图。状态：**刷新来源尚未闭合**，下面区分“已证实”和“待证”。

## 一句话结论

自 2026-10-23 18:38 UTC 常驻 broker 启动以来，agy 这条链路只对 BOSS 导航过 **1 次**；但到 10-24 06:21 UTC 时，BOSS 标签在没有任何工具导航的情况下仍停在“加载中，请稍候”。所以最近 GUI 上看到的反复刷新，**大概率不是 agy 的导航造成的**，更可能来自 BOSS 页面自身的加载流程，或者同一个 Chrome 上的其他控制方（Codex 内置浏览器、ChatGPT 扩展、Claude in Chrome）。更早那段时间（10-23 晚）则确实有工具侧的密集导航。缺口在于：同一个真实标签同时被多方操作，却没有任何“谁在用这个标签”的归属和导航预算。

## 已证实的事实

| # | 事实 | 证据 |
|---|---|---|
| F1 | BOSS 标签停在加载态：顶层 `RootWebArea "BOSS直聘" busy`，正文只有“加载中，请稍候”，里面嵌着一个 `about:blank` iframe，没有职位正文 | `TRI25_20261023/controlled-boss-stored-text-20261024.txt`；`controlled-text-replay-20261024.json`（`top_root_busy: true`、`blank_child_root_detected: true`、`has_body: false`） |
| F2 | 这次读取前后没有导航：06:21 与 06:23 UTC 只有 `list_pages → select_page → take_snapshot` | `trusted-connection-debug.log` 第 776–813 行 |
| F3 | broker 启动后只有一个后端；此后对 BOSS 的导航只有 04:46 UTC 的 1 次（pageId 1） | `persistent-browser-events.jsonl`（1 次 `BACKEND_STARTED`，5 次 `CLIENT_ATTACHED`）；`trusted-connection-debug.log` 第 735–738 行 |
| F4 | broker 之前（10-23）工具侧导航很密集：真实 chrome-devtools 连接共有 40 次 navigate/new_page；其中 10-23 13 时（UTC）一小时内有 17 次 `navigate_page` **没带 pageId**，作用在当时“被选中”的标签上 | `antigravity-session/logs/mcp_lifecycle_timeline.jsonl`，已排除 fixture 测试进程 |
| F5 | 历史上起过 17 个 auto-connect 进程和 3 个“既没有 auto-connect 也没有 browser-url”的进程；后者会让 chrome-devtools-mcp 自己另开一个 Chrome 窗口 | 同上，`MCP_WRAPPER_INIT.passthrough_args` |
| F6 | 同一个 Chrome 里累积了 6 个 about:blank、2 个 newtab、1 个本地演示页（127.0.0.1:18765）和多个智联公司页 | `CONTROLLED_8D647A54/driver.json` 的 `inventory_before` |
| F7 | agy 会改写工具输出里的 `%`：`%E4` 变成 `%!E(MISSING)`（Go 格式化函数的特征）。模型看到的 URL 已经损坏 | `controlled-boss-stored-text-20261024.txt`、`controlled-zhaopin-stored-text-20261024.txt`，以及 `~/.gemini/antigravity-cli/brain/.../transcript.jsonl`。目前**没有**发现有导航用了损坏的 URL |
| F8 | agy 输出里有乱码：页面标题 “BOSS直聘” 被读成 “BOSSֱƸ” | `CONTROLLED_8D647A54/driver.json` 的 `visible_heading` |
| F9 | **停止标志误报**：智联列表页底部有一个正常的“企业招聘”链接指向 `passport.zhaopin.com`，整页文本子串匹配就判成了 `USER_INTERVENTION_REQUIRED` | `CONTROLLED_5C318DF8/driver.json`；`controlled-zhaopin-stored-text-20261024.txt` 第 337 行 |

## 刷新来源：候选与判别

| 候选 | 状态 | 支持 | 反对或缺口 | 判别方法（只观察） |
|---|---|---|---|---|
| A. 工具侧重复导航 | 10-23 已证实；10-24 基本排除 | F4、F5 | F3：broker 之后只有 1 次 | 刷新时看 `trusted-connection-debug.log` 有没有同时间的 `navigate_page` |
| B. BOSS 页面自身的加载或校验流程卡住后循环重载 | 待证 | F1、F2：没有导航，页面仍是 busy，且有空白子框架 | 没有主文档导航事件，无法区分“卡住”和“反复重载” | 本人在**没有任何自动化连接**的情况下打开同一标签，观察是否正常；再在只附着、不操作时观察 |
| C. 同一 Chrome 上的其他控制方 | 待证 | 10-20 诊断记录过 Codex 内置浏览器反复刷新、65 次路由错误；ChatGPT 扩展含 `foreign-frame-monitor.js`，会把 frame 置成 about:blank（与 F1 的空白子框架吻合） | 没有运行态证据显示它作用在 BOSS 的 iframe 上 | 暂时只保留一个控制方（例如关掉 ChatGPT 扩展对该标签的控制），观察刷新是否消失 |
| D. 定时巡检或子任务重复唤醒 | 待证 | 巡检每 15 分钟唤醒，子代理和驱动会重发回合 | 本轮没有查定时任务清单 | 核对刷新时刻是否落在巡检整点或 15 分钟节拍上 |
| E. `select_page bringToFront` 抢焦点，看起来像刷新 | 可能，影响较轻 | 每次读取前都要前置 | 前置不会重载页面 | 对照刷新时刻与 `select_page` 时间戳 |
| F. 巡检看板 30 秒自动刷新 | 排除 | `scripts/patrol_dashboard.py:190` 有 meta refresh | 它只作用在本地看板页 | — |

## 结构性缺口

- [ ] **S1 一个真实标签同时被多方控制，没有归属。** 仓库只有“发送”的站点租约（`outreach lease`），没有“读取”的标签租约。Codex 内置浏览器、ChatGPT 扩展、agy 的 chrome-devtools、Claude in Chrome、Computer Use 都可以同时作用在同一个 BOSS 标签上；另一个代理在 10-24 14:20–14:30（本地时间）还在跑受控检查。
  - 修法：为每个站规定一个读取方，并加一个本机标签租约文件（站、pageId、持有者、到期时间），没拿到租约的一方只能 `list_pages`。
- [ ] **S2 页面状态存在每个 wrapper 进程的内存里，跨进程即丢失。** `PageReadiness.pages` 不落盘，起过 33 个宿主进程，每个都从零开始，“这个标签刚导航过”的事实也一起丢了。
  - 修法：把每个 pageId 的绑定 origin、最近导航时间、停止原因写进 broker 的持久状态；每个标签每轮最多导航 1 次，重复导航直接拒绝。
- [ ] **S3 没有“加载中”状态。** busy 加空白子框架被当成 `PAGE_NOT_READY`，驱动和模型的自然反应就是重试，在旧入口里重试就意味着再导航一次。
  - 修法：识别为 `PAGE_LOADING`，按固定次数间隔重读文字快照（不导航、不刷新），超过次数就停掉该目标，并在汇报里写“页面持续加载”，不归因为风控。
- [ ] **S4 停止标志按整页文本子串匹配，既误报又漏报。** 误报：F9，正常页脚链接就触发停止。漏报：BOSS 卡在“加载中”不在停止标志里，系统会继续戳它。
  - 修法：带域名或路径的标志（如 `passport.zhaopin.com`、`passport/zp/security`、`safe.liepin.com`）只匹配顶层 `RootWebArea` 的 URL；文字标志只匹配可见正文，排除 link 的 url 属性。先在 `test_page_readiness.mjs` 写失败用例：“智联列表页含 passport 登录链接 → 仍可读”。上一份清单 G-1（`jobs.zhaopin.com` 详情页）一并修。
- [ ] **S5 宿主改写 `%`，模型看到的 URL 已经损坏。** 现在只是潜在风险，但一旦模型从快照里取链接再导航，就会打开一个错误的 URL，BOSS 的单页应用可能因此持续加载。
  - 修法：URL 只从 `list_pages` 或来源清单取，不从快照正文取；wrapper 对 `navigate_page` 的 URL 拒绝含 `%!` 的输入。同时把这个问题记给 agy 维护方。
- [ ] **S6 Windows 输出编码不一致**（F8）。标题、公司名等用于校验的字段不可信。
  - 修法：驱动读取 agy 输出时显式按 UTF-8 解码；校验字段改用 URL 和 pageId，不依赖标题文字。
- [ ] **S7 标签累积，没有归属和清理。** F6；未带 pageId 的导航（F4）会作用在“当前选中”的任意标签上，可能就是本人正在看的 BOSS 页。
  - 修法：当前 `page_readiness.mjs` 已拒绝未绑定的 navigate/select（existing-pages-only 模式），保持；空白页和演示页由本人手动关闭，工具不代为关闭。
- [ ] **S8 进程启动方式不统一。** F5 中“既没有 auto-connect 也没有 browser-url”的启动会另开 Chrome 窗口，GUI 上看起来就是“自动打开浏览器”。
  - 修法：只允许经 `start_connection_owner.py` → broker 启动；其他启动参数组合由 wrapper 直接拒绝。

## 不做的事

- 不拦截、替换或注入 BOSS 页面脚本，不隐藏调试连接，不改指纹，不为了让页面“加载完成”去处理站点校验。
- 页面卡在加载态或重载循环时，按停止条件交人，不加大重试。
- 不为观察刷新而关闭本人的 Chrome 或重启已获准的连接。

## 下一步（建议顺序）

1. [ ] 判别 B 和 C：本人在只附着、不操作的条件下观察 BOSS 标签 2 分钟，然后暂停其他控制方再观察一次，把结果记在本文。
2. [ ] 修 S4（含 G-1），先写失败测试，因为 F9 的误报已经影响当前的智联读取。
3. [ ] 修 S2 和 S3，把“每标签每轮最多导航一次”和 `PAGE_LOADING` 落到 broker 与 wrapper。
4. [ ] S1 的读取租约需要和 Codex、Claude 两侧的使用方式一起定，由本人决定每个站的读取方。

---

## 观察结果（2026-10-24 14:37–14:39 本地时间）

本人反馈：Claude in Chrome 的各条流程都能执行，但 BOSS 标签两分钟内一直在刷新，没有新职位落库。同一时段的本地记录如下。

- **刷新的真实形态是安全验证页循环。** 同时段另一个代理的受控读取（`CONTROLLED_9E3158B1/driver.json`）显示：pageId 25 在标签列表里是 `https://www.zhipin.com/web/geek/jobs`，实际根地址却是 `https://www.zhipin.com/web/passport/zp/security.html`，标题是“请稍候 - BOSS直聘”。页面在职位页和安全验证页之间来回跳转，这就是 GUI 上看到的反复刷新。它正好命中 `boss.yaml` 的停止标志 `passport/zp/security`。
- **这两分钟里没有任何工具导航。** broker 只收到 `list_pages`、`select_page`（pageId 6 智联、pageId 25 BOSS，`bringToFront: true`）和一次智联的 `take_snapshot`，没有 `navigate_page` 和 `new_page`（`persistent-browser-events.jsonl` 06:37:15–06:38:42 UTC，`trusted-connection-debug.log` 同时段）。
- **这不是一次干净的对照。** 观察期间：
  - 常驻 broker（PID 36792）→ wrapper（10404）→ chrome-devtools-mcp（25888）一直以 auto-connect 附着在日常 Chrome 上；
  - Codex 的 Computer Use 与浏览器运行时进程也在运行；
  - 另一个代理在跑受控检查，`select_page bringToFront` 会把 BOSS 标签切到前台。
  所以“只有 Claude in Chrome、没有其他控制方”的条件并不成立。
- **没有新落库是正确行为。** 库里 BOSS 职位共 200 条，最后一次写入是 2026-10-22 09:46 UTC，今天 0 条；智联今天 2 条。命中验证页本来就应停站，不应入库。
- **时间上的关联（待证，不是结论）**：BOSS 到 10-22 都还能经既有巡检通道正常入库；从 10-23 起，chrome-devtools 开始以 auto-connect 附着日常 Chrome（生命周期日志最早 10-23 09 时 UTC），此后 BOSS 再没有入库，现在停在验证页循环。两者时间重合，但没有排除其他变化（账号、平台规则、其他扩展）。

### 更新后的判断

| 候选 | 更新 |
|---|---|
| A. 工具侧重复导航 | 本次排除：两分钟内 0 次导航 |
| B. BOSS 自身校验流程 | 已证实存在：页面在 `security.html` 与职位页之间循环；**为什么**循环（账号状态、平台风控、浏览器上的调试附着）仍待证 |
| C. 同一 Chrome 上的其他控制方 | 仍是主要嫌疑：常驻 CDP 附着从未断开，观察期间还有前台切换 |

### 按停止条件该做的

- [ ] BOSS 今天停站：命中 `passport/zp/security` 即为 `USER_INTERVENTION_REQUIRED`，不重试、不刷新、不导航。
- [ ] 不在验证页上做任何自动操作。验证如果需要人完成，由本人在平台上自己处理。
- [ ] 干净对照（由本人决定是否做）：先停掉其他代理的受控检查，再停掉常驻 broker（释放 auto-connect；以后重连需要在 Chrome 里再点一次“允许”），只留 Claude in Chrome 或者完全不留自动化，然后本人手动打开 BOSS 职位页观察 2 分钟。
  - 循环消失：说明调试附着与 BOSS 校验冲突，BOSS 不再走 chrome-devtools 通道。
  - 仍然循环：属于账号或平台侧，交本人在平台上处理。
- [ ] 观察期间不能有任何代理对同一个 Chrome 执行 `select_page` 或读取（S1：读取租约缺失，这一点在这次观察中直接干扰了结果）。

---

## ~~结论（2026-10-24，本人复核后）~~ 已撤回，见下方「更正」

本人确认：账号登录正常，手工操作正常；只要换成自动化控制，页面就进入 `security.html` 刷新循环，后续的点击、截图、换检索词和读取结果都不会发生。

据此判定：**BOSS 的安全校验在识别到自动化控制后拦截了它**。这是平台的风控信号，不是本地代码的故障。

- 不再尝试让自动化通过这一步。不隐藏调试连接、不伪装指纹或浏览器环境、不模拟人工节奏去规避校验、不换账号、不换工具来躲检测。这些都在 AGENTS.md 的硬性边界之外，也与 `boss.yaml` 的接入评估一致（“按接入阶梯逐档评估后判定不可自动接入”）。
- 继续自动化尝试会反复触发验证，可能让平台给账号加风控标记。BOSS 应立即停止一切自动化读取和点击。

### BOSS 改为人工协同

| 环节 | 人做什么 | 仓库和智能体做什么 |
|---|---|---|
| 检索词 | — | `jobs search-plan` 给出本轮检索词 |
| 搜索与打开详情 | 本人在 BOSS 网页或 APP 里手工搜索、打开职位 | 不碰 BOSS 页面 |
| 取 JD | 复制职位描述正文、职位名、公司、链接 | `jobs add-jd --source boss` 入库（以后可加批量导入，见下） |
| 记检索 | 告知每个词搜到几条、新增几条 | `jobs search-log boss …` |
| 评估与排序 | — | `jobs triage` 照常 |
| 首条招呼 | 审批后由本人在 BOSS 上手工发送 | 起草、`outreach draft-batch → ask → approve`；本人发完后 `outreach record` 记账 |
| 读新消息 | 本人查看消息列表，把新来信原文交给智能体 | `conversations inbound` 记录、分级、起草回复 |

### 需要跟进的改动（未实施）

- [ ] `page_readiness.mjs`：对 `www.zhipin.com` 的页面一律拒绝 `select_page`、`take_snapshot`、`click`、`fill`，返回 `MANUAL_ONLY_SOURCE`，防止任何代理再去碰 BOSS 标签。
- [ ] 采集驱动与巡检说明：BOSS 从自动采集计划中移除；`references/browser-sourcing.md`、`references/patrol.md`、能力目录同步写明“BOSS 人工协同”。
- [ ] 可选：`jobs add-jd` 支持一次导入多条人工粘贴的 JD（新能力，按 AGENTS.md 先写测试，并同步能力目录）。


---

## 更正（2026-10-24）

上面“BOSS 的安全校验识别到自动化控制后拦截了它”的结论**撤回**。理由如下。

- **没有出现任何验证内容。** 本人确认没有验证码、登录框或风控提示。日志里的 `security.html` 是 BOSS 静默的“请稍候”中转页（`/web/passport/zp/security.html?callbackUrl=…&appName=zhipin_geek_spa_web&code=37&seed=…`，见 agy 转录 `brain/30c17b0e-…/transcript.jsonl` 10-23 11:44 UTC 的真实工具输出）。正常情况下它一闪而过、跳回原页，不是给人看的验证。路径里带 `passport` 只说明命中了这个中转页，不能等同于“触发了验证”。
- **自动化本身以前是通的。** 10-21、10-22 两天，BOSS 经既有巡检通道各搜索了 11 次和 15 次，入库职位 200 条，最后一条写入是 10-22 09:46 UTC。
- **时间点吻合。** chrome-devtools 以 auto-connect 附着日常 Chrome 是从 10-23 11:03 UTC 开始的；最早一次观察到“请稍候”页卡住是 10-23 11:44 UTC，是工具新建的标签（`new_page`）。

### 本人截图提供的对照（2026-10-24）

同一个 Chrome 窗口顶部显示“自动测试软件正在控制 Chrome”（调试连接仍附着）：

| 标签 | 谁打开的 | 状态 |
|---|---|---|
| 第 1 个 | 工具新建或导航 | 停在 `/web/passport/zp/security.html`（“请稍候”中转页） |
| 第 2 个 | 本人手动 | `zhipin.com/web/geek/jobs?query=Agent产品经理&city=101020100` 完整加载：列表、右侧 JD 详情都正常 |

由此可以缩小范围：

- 浏览器处于被调试附着的状态，**本身不会**让 BOSS 卡住，第 2 个标签就是证据。
- 卡住只发生在**由工具发起的新建或导航**上。可能的机制（待证）：工具创建的标签使用了不同的上下文，或者它的子框架、脚本在调试器附着时被挂起没有恢复，中转页的脚本因此跑不完，就在原页和中转页之间来回跳。本次没有拿到 CDP 事件，不能断言是哪一种。

### 能否读取（fetch）

可以，前提是**由人导航、工具只读**：

1. 本人手动搜索、点开职位卡片，让右侧 JD 完整显示。
2. 工具只做：`list_pages` → `select_page`（绑定这个人工打开的标签）→ `take_snapshot` 读文字。这正是当前 `interactive_worker.py` 的 existing-pages-only 规则。
3. 职位链接从快照里卡片的 `/job_detail/…` 链接取，去掉 `?` 之后的部分，再经 `jobs import-observations` 入库；取不到就用 `jobs add-jd --source boss`。
4. 工具不做 `new_page`、`navigate_page`，不点“立即沟通”（会触发发送），不翻页、不换检索词。换词、翻页、换卡片都由人来做。

### 需要跟进

- [ ] 用一次只读读取验证这个结论：在本人手动打开的 BOSS 标签上做一次 `take_snapshot`，确认不会触发跳转，并能读到 JD 正文。
- [ ] 如果验证通过：在 `page_readiness.mjs` 里对 `www.zhipin.com` 禁止 `navigate_page`、`new_page` 和 `click`，只允许读取；在 `browser-sourcing.md` 里写明“BOSS：人导航，工具只读”。
- [ ] “工具发起的导航为什么会卡住”需要 CDP 层面的诊断（目标创建方式、浏览器上下文、子目标是否挂起）。在弄清之前，不对 BOSS 做工具导航。

---

## 方向调整：BOSS 寻源必须由 agent 完成（2026-10-24）

本人明确：搜索、点开、读 JD 这些寻源动作必须由 agent 完成，不能交给人，否则项目不成立。上一节“由人导航、工具只读”的建议**作废**。

### 依据：agent 寻源原本是通的

- `references/browser-sourcing.md` 规定的主路径是“宿主在用户自己登录的浏览器里搜索和读取，**Claude in Chrome 优先**”。
- 按这条路径，10-21、10-22 两天 BOSS 共自动搜索 26 次、入库 200 条（`job_searches`、`normalized_jobs`）。
- 出问题的时间点与一个新增因素重合：从 10-23 11:03 UTC 起，chrome-devtools 以 auto-connect 常驻附着日常 Chrome（broker PID 36792 → 10404 → 25888，至今仍在运行，窗口顶部因此一直显示“自动测试软件正在控制 Chrome”）。此后不论哪个 agent 发起导航，BOSS 都卡在“请稍候”中转页。

### 修复方案（不涉及任何规避）

1. **一个 Chrome 只允许一个自动化控制方。** 日常 Chrome 上撤掉 chrome-devtools 的常驻附着：停掉 broker，并在 `chrome://inspect/#remote-debugging` 关闭远程调试开关。Gemini/agy 不再连接日常 Chrome。
2. **BOSS 回到文档规定的主路径**：Claude in Chrome 由 agent 按 `browser-sourcing.md` 第 1～7 步执行，即搜索、翻页（不超过 3 页、间隔不少于 20 秒）、点开详情、读 JD、`import-observations`。节奏、额度、停止标志全部照旧。
3. **一次 agent 验证**：撤掉附着后，由 agent 用 Claude in Chrome 新开标签打开清单里的搜索地址，读列表，再打开 1 个详情读 JD，然后入库。
   - 能读到：确认是两个调试客户端冲突导致的回归。之后 BOSS（以及同样受影响的猎聘）固定走 Claude in Chrome，chrome-devtools 只能在另一个 Chrome 实例上用。
   - 撤掉附着后仍然卡住：说明是平台侧的变化，按停止条件如实汇报，不做任何规避。
4. **结构性补丁**：
   - [ ] 浏览器控制方租约：同一个 Chrome 同一时间只有一个自动化控制方（Claude in Chrome、chrome-devtools、Codex 浏览器三选一），写进 `browser-sourcing.md` 与巡检说明；启动 broker 前检查有没有其他控制方。
   - [ ] `start_connection_owner.py`：日常 Chrome 若由 Claude in Chrome 负责寻源，就拒绝以 auto-connect 附着它。
   - [ ] 巡检汇报区分“页面卡住（本地控制冲突待查）”和“命中停止标志（平台）”。

### 边界

- 不隐藏调试连接、不改 `navigator.webdriver` 或指纹、不注入脚本、不拦截跳转。
- 节奏和额度不为“跑通”而放宽，“立即沟通”等对外按钮仍然不点。


## Codex 离线复核补充（2026-10-24）

完整回执：[BOSS调查代码复核](../candidate/private/codex-harness/runs/TRI25_20261023/boss-investigation-review-20261024.txt)。本轮没有浏览器请求、没有恢复采集，也没有停止连接。

1. 更正此前措辞：14:38:32实际证据是选页响应中的页面列表地址命中 `security.html`；当轮没有AX快照，不能把模型返回的 `snapshot_root_url`、标题或推测的验证码当作观测。当前来源清单规定该URL停止，因此保留停站，但不将停止策略等同于已证实账号风控。
2. 手动标签在同一已附着Chrome内正常，支持“附着与正常显示可以共存”；不能据此把每次工具导航失败或双客户端冲突直接定为已证实因果。
3. 新的具体代码候选：`tools/pages.js:49` 的选页先执行 `page.init()`；`McpPage.js:290/298` 初始化会调用 `emulateFocusedPage(true)`。因此选页除了前台切换还可能进行逐页CDP初始化。源码中这是内部行为，关闭emulation工具类别并不阻止该调用。是否影响中转页/子目标仍待证；未更改这段行为或绕过站点校验。
4. 上下文假说需限定：`McpContext.js:193-205` 只有显式传入 `isolatedContextName` 才创建独立BrowserContext；正常newPage分支不能直接推断登录环境不同。
5. F8需要更正：UTF-8原件中的“BOSS直聘”与智联中文标题正常，控制台展示曾受Windows输出编码影响；未证实原件标题损坏。F7的 `%!(MISSING)` 残片确实存在于保存的工具文字，但未证明该损坏URL被实际导航使用，也未定位到完整字节链路的具体层。
6. 释放常驻连接涉及此前要求保留的broker；现已单独向本人确认仅停止本轮36792→10404→25888的范围，保留Chrome/标签/其他代理。附件中的建议不自动视为改变既有授权。未关闭Chrome远程调试开关，也未向Claude会话发送消息。

不新增轮询、固定间隔重读或自动导航重试；不将已作废的人工寻源路线改成项目要求。单次隔离后恢复也不能单独证明唯一原因是双客户端冲突。

本人后续明确选择：保留连接，只做离线核验。上述连接释放范围仅为待选方案，本轮未执行；受控检查已结束，无待完成请求。
