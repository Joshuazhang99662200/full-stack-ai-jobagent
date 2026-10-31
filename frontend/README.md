# 岗位任务队列

React 只读面板与可嵌入组件。岗位事实来自现有 pipeline，执行活动来自宿主的明确记录；查看页面不触发招聘网站请求，不登记审批或发送。

本组件采用白底、浅灰历史记录和浅蓝进行中状态，只维护 `src/` 中这一套实现。绿色旧版与早期独立 HTML 原型已废弃，不作为模板、主题或备用入口复用。文案调整沿用当前样式，配色回归测试同时覆盖岗位任务、运行记录和沟通进展。

默认主视图一行一个岗位，像 Agent 汇报：我做到了哪里（岗位业务状态及其时间）、已完成和正在做的工作、接下来准备做什么、需要你处理什么。不画分钟刻度或耗时色条。顶部按“正在推进 / 需要你 / 等待对方”计数，点击即可筛选；需要你的岗位排在最前，已关闭的岗位沉底，同组内参考最近已保存的硬筛结果与匹配值排序。

“接下来”只读取宿主在阶段记录里明确登记的 `next_step`，没有登记时显示“下一步尚未安排”，不由界面推断。“需要你”只来自明确的等待事件、待核对的硬筛、暂停、待面试或多条未结束联系记录，并写清需要你做什么。一个岗位跨轮次的工作可以同时出现，run_id 作为追溯信息保留；缺少评分不会补零，执行失败也不会把岗位自动关闭。

## 构建和运行

需要 Node.js 22.12+ 和已配置的 Python 项目环境。在本目录执行：

```powershell
npm.cmd ci
npm.cmd run build
```

回到仓库根目录，按 `jobagent console serve --help` 指定候选人、数据库、工作区及静态目录 `frontend/dist`。启动参数详见仓库 `docs/polling-console.md`。

开发预览运行 `npm.cmd run dev`。明确使用 `?demo=1` 才会显示合成示例；真实查询失败不会自动改成示例。示例快照和字段契约由仓库的 Python 生成脚本导出，不能手工改成另一套领域模型。

页面刷新仅重新读取本地快照。刷新按钮不会改变轮询频率、读取额度、平台状态、动态参数或任何业务记录。

更新前端构建后，已打开的页面需要重新加载才能使用新代码；页面内的“刷新”只更新数据。交付时须重新加载用户实际打开的预览标签页，核对标题和样式，不能只验证另开的浏览器页面。

## 嵌入宿主

```tsx
import { Console, type Snapshot } from '@jobagent/polling-console';
import '@jobagent/polling-console/styles.css';

// snapshot / definitions 由宿主调用同一只读查询接口获得。
<Console snapshot={snapshot as Snapshot} definitions={definitions} />
```

`Console` 默认不读写浏览器 URL，可进行服务端静态渲染；独立页面显式传入 `syncUrl`，在 URL 保存选中的视图和记录。调用方管理快照刷新，传入 `onRefresh` 和 `refreshing` 可展示刷新按钮。`initialView` 可设为 `queue`（默认）、`runs`、`jobs`、`fields`，`onViewChange` 接收视图变化。

组件样式限定在 `.ja-console`；所有 CSS 变量使用 `--ja-` 前缀。独立页面的 html/body 样式留在 `app.css`，不进入库输出。导出目录是 `lib/`，独立页面输出为 `dist/`。

全部业务字段通过详情中的完整字段区和原始 JSON 保留。字段类型、枚举和引用关系由 Python 的 JSON Schema 提供，前端只定义传输外壳。长正文按原文换行显示，不截断内容。

## 验证

```powershell
npm.cmd run typecheck
npm.cmd run build
# 使用 Playwright 已安装的浏览器，或者显式指定本机 Chromium / Edge：
$env:CONSOLE_BROWSER = 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
npm.cmd test
```

测试覆盖真实查询失败、加载/空状态、URL 恢复、完整 JD 与草稿、跳过简历交换的九态历史和 320–1920px 布局。测试只使用合成数据。

阶段条只根据已记录事件绘制。开始时间缺失显示短线与说明；停止收到心跳的开放阶段显示“状态未确认”，保留原运行状态。审批详情来源尚未接通时明确显示来源限制。
