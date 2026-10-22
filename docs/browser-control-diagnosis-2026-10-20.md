# 浏览器搜索受阻：后端诊断记录

日期：2026-10-20。状态：已定位失败层与调用顺序，根因尚未闭合，未修复。

## 已观测现象

1. 早期不同 Chrome 扩展实例返回的标签页集合不同，有的为空，有的只有扩展安装页。后续一个实例实际返回 BOSS、猎聘和智联的现有页面；实例变化与账号切换有时间相关性，不能据此认定账号是根因。
2. 在已认领的 BOSS 现有页面，`domSnapshot` 成功读到登录状态、上海岗位列表及 Momenta 职位描述。
3. 随后的 `locator.fill` 被宿主工具拒绝，提示 `unsupported_protocol` 对应的错误文本：请求的 URL 协议不允许，仅允许 HTTP/HTTPS。该输入没有执行，后续点击搜索也没有执行。
4. Windows Computer Use 是另一条失败链：读取 Chrome 窗口状态时，工具称无法可靠确认当前浏览器 URL 并终止。尚无证据证明它与第 3 项是同一个根因。
5. 用户观察到内置浏览器反复刷新。本次检查没有取得网页导航事件记录，无法确认刷新由网站、宿主还是其他组件发起，也无法据此证明已经触发网站风控。

## 仓库边界

本项目没有三站浏览器的输入执行器。`src/jobagent/bridge/mcp_server.py` 只暴露账本读取与信箱工具；`src/jobagent/cli/jobs.py` 的 `import-observations` 消费宿主采集的 JSON，完成来源校验、归一化、保存和去重标识。

所以本次失败发生在求职业务后端之前，修改 triage、审批、数据库或绕过来源规则不能修复它。

## CC 的实际执行方式

对本机此前项目会话作定向检查，找到 `mcp__claude-in-chrome__navigate` 对 BOSS 搜索页的调用，参数包含 query 与 city；2026-10-16 的对应结果为非错误回执并包含导航成功信息。该会话还使用了独立的 `javascript_tool`、`computer` 和 `browser_batch`。

这证明 CC 使用了自己的 Chrome 扩展工具链并至少成功导航过 BOSS 搜索页，不能把 CC 的执行能力等同于 Codex 当前工具链。没有调用这些历史脚本，也没有复用它们来重试被阻断的操作。

## Codex 本机插件源码中的调用链

检查对象：`openai-bundled/browser/26.1013.40934/scripts/browser-service.mjs`，以及本机 ChatGPT Chrome 扩展 `1.26.1005.11759` 的静态代码。两个已安装 Chrome 配置中的 `background.js` 摘要相同，不能仅凭配置不同推断其执行逻辑不同。

```text
playwright_locator_fill                         browser-service.mjs:1329
    |
security.currentTabUrl(tabId)                   browser-service.mjs:1110
    |
security 的 URL 数据源 = getCommittedTabUrl     browser-service.mjs:4478
    |
向扩展发送 getCommittedTabUrl 请求              browser-service.mjs:4494
    |
确认标签页归当前会话所有
    |
返回 chrome.tabs.get(tabId).url                  扩展 background.js:38
    |
actInFrame(url).assert() --> URL 协议策略         browser-service.mjs:1110
    |
通过后才调用 prepareLocatorFill                 browser-service.mjs:1329
    |
定位输入框、检查可编辑性、执行输入
```

协议判断函数位于 `browser-service.mjs:1042`：HTTP/HTTPS 被允许，精确的 `about:blank` 也是特殊允许项；其他可解析协议返回 `unsupported_protocol`。该判断路径不比对 Google 账号。

由此可以确认：本次错误文本来自输入前的地址授权阶段，尚未执行搜索框定位。不能归因为选择器写错，也没有证据归因为 BOSS 拒绝了这次输入请求。

标签列表显示的地址与操作前读取地址是两个请求，时间也不同。此前看到 HTTPS 标签元数据，不能替代失败瞬间 `getCommittedTabUrl` 的返回值。目前缺少后者，不能声称已经确认某个具体协议、标签 ID 错配或页面跳转。

## 扩展之间的影响与刷新问题

静态代码确实包含 `foreign-frame-monitor.js`：当已受控页面出现其他扩展的 iframe 时，它会把该 iframe 设置为空 srcdoc，或把 frame 的 src 设置为 about:blank。这证明存在跨扩展 iframe 屏蔽机制，但不证明当前故障由它触发；此处也不构成对 Google 账号的比对。

在已检查的后台文件和该监控脚本中，没有找到周期性刷新 BOSS 主页面的调用。后台有更新扩展自身的 `chrome.runtime.reload()`，它与网页刷新是不同动作；不能仅凭 reload 字样认定为刷新原因。仓库的巡检看板自身含 30 秒 meta refresh，作用对象是本地看板，也不能据此解释 BOSS 页重载。

## 尚缺证据与修复方向

根因闭合需要工具维护侧在既有失败路径记录以下最小诊断数据，不再次操作招聘网站：

- 请求所属扩展实例、宿主会话、tab_id 与请求时间。
- `getCommittedTabUrl` 返回值的协议分类，以及与同一标签元数据的地址摘要是否相同。查询参数和令牌不得进入日志。
- 失败前后的主文档导航事件，区分真实页面切换、扩展重连及标签映射变化。
- Windows URL 识别失败需单独采集识别来源与错误类别，不能与扩展协议拒绝合并。

当前受支持的公开接口没有提供被拒请求的这份内部诊断数据；本次只读检查的本地日志也没有找到相关字段。不能通过私有协议调用、底层调试命令、替换 URL 数据源或关闭校验取得可操作权限。

修复方向是确认并修复地址数据或标签绑定的一致性，保留 URL 协议校验。若缺陷位于宿主或扩展，需要维护方修复；本仓库新建控制工具不能自动修复该故障。

## 本次操作范围

仅检查仓库、本机插件静态代码、接入配置的非秘密字段及定向历史调用记录。未访问认证文件或 Cookie，未执行历史浏览器脚本，未操作招聘页面，未刷新、登录、搜索或发送。未改动插件、浏览器设置或任何安全校验；新工具实现暂缓。
