# Muse 通用 React 模板

默认页面以用户指定的当前 Muse 分享页为视觉与结构基准，直接复用 zip 的 React 查询、排序、筛选、材料展示和决定回读逻辑。详情、独立待办、执行清单及运行/沟通/说明页均可交互。

来源、差异、接入限制及核验方法见 [源码还原记录](../docs/muse-source-template-2026-11-02.md)。默认入口 `?demo=1` 使用合成数据；`?demo=1&template=zip` 查看 zip React 版本；`?legacy=1` 保留先前 Console 的兼容视图。真实来源失败不会自动进入演示。

```powershell
npm.cmd ci
npm.cmd run typecheck
npm.cmd run build
npm.cmd run test:ssr
npm.cmd run dev -- --port 5178
```

独立构建输出 `dist/`；兼容 Console 库输出 `lib/`；Muse 库输出 `muse-lib/`。字段类型通过 `python scripts/build_muse_contracts.py --check` 核对 Python 权威传输模型。

```tsx
import { MusePanel, type MuseActions } from '@jobagent/polling-console/muse';
import '@jobagent/polling-console/muse/styles.css';

<MusePanel actions={hostActions as MuseActions} cvFiles={hostPreviewFiles} />
```

宿主提供 `MuseActions`，或向 `MuseSourcePanel` 注入已有 `ConsoleDataSource`。查看与筛选不执行招聘操作。真实保存、审批、发送与回读必须调用已有业务服务。未接入能力禁用或明确说明，不能用前端状态变更代替成功。

当前页样式限定在 `.muse-current`。zip 对照入口包含其原 Tailwind 基础样式，Muse 样式包适合独立面板；宿主需要完全隔离样式时在 iframe 内挂载。React 和 React Query 作为 Muse 库的外部运行时依赖；分发构建资产时保留 `THIRD_PARTY_NOTICES.md`。

## 兼容 Console 参考接口

以下为 `?legacy=1` 及原 `<Console>` / `<SourceConsole>` 组件说明；不表示当前 Muse 模板沿用这些布局。

React 岗位面板与可嵌入组件，支持只读快照及可注入的宿主交互接口。岗位事实来自现有 pipeline，执行活动来自宿主的明确记录；查看页面不触发招聘网站请求，不登记审批或发送。

本组件采用白底、浅灰历史记录和浅蓝进行中状态，只维护 `src/` 中这一套实现。绿色旧版与早期独立 HTML 原型已废弃，不作为模板、主题或备用入口复用。文案调整沿用当前样式，配色回归测试同时覆盖岗位任务、运行记录和沟通进展。

默认主视图一行一个岗位，像 Agent 汇报：我做到了哪里（岗位业务状态及其时间）、已完成和正在做的工作、接下来准备做什么、需要你处理什么。不画分钟刻度或耗时色条。顶部按“全部 / 正在推进 / 等你处理 / 等待对方 / 已结束”计数，点击即可筛选；默认按已保存匹配度排序，可切换入库时间；缺值排在同组末尾，已关闭的岗位沉底。

“接下来”只读取宿主在阶段记录里明确登记的 `next_step`，没有登记时显示“下一步尚未安排”，不由界面推断。“需要你”只读取宿主明确提供、已排除自身信息缺口的个人待办；暂停、待核对或未读取记录本身不会生成红点。未接入待办源时明确显示未知。一个岗位跨轮次的工作可以同时出现，run_id 作为追溯信息保留；缺少评分不会补零，执行失败也不会把岗位自动关闭。

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

岗位列表显式展示 BOSS、智联或猎聘渠道，点击岗位、渠道或“需要你”打开详情弹窗。弹窗保留进展、材料、历史、Signal/Harness 及原始记录；支持 Escape、焦点返回和键盘页签操作。猎聘路由隐藏业务视图中的招呼步骤和材料，原始记录页仍保留未经改写的源字段。未知渠道不默认开放招呼内容。

每个详情弹窗底部保留工作流程：已记录完成的步骤用蓝色，未开始或缺少记录用灰色，正在执行及等待处理的步骤加描边并标“现在”。允许多个步骤并行；没有记录标“未记录”，不按九态位置补造前置完成。失效心跳标“状态未确认”，已关闭岗位不标当前工作；下一步仅展示宿主明确登记的计划。流程记录不能代替本人批准或投递回读。

界面路由不代表后端已支持对应平台的全部操作：当前 Python pipeline 仍只支持 Boss、智联，私有 Muse 库须经独立适配后才能进入真实查询。默认只读源没有审批、放弃或投递写入能力；宿主接口是否可用按数据源明确声明。Signal 未接入时明确提示，Harness 仅展示明确绑定该岗位的既有运行和产物。

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

## 宿主交互接口

新增 `SourceConsole` 通过 `ConsoleDataSource` 读取快照、定义、详情、材料、个人待办、渠道与批次。已有 `<Console snapshot={snapshot} />` 和 SSR 嵌入保持可用。真实 HTTP 源仅使用已有 GET 接口，不增加写入端点。

`?demo=1` 使用只允许 `CAND_DEMO` 的合成适配器；决定和演示批次按候选人隔离保存在浏览器。损坏存储会报告错误，不静默重置。普通刷新只读数据；核对同步是单独操作。演示不访问招聘网站，不打开登录窗口。

决定和执行使用独立接口。决定保存结果未知时仅允许核验；执行清单绑定准确正文、附件摘要、材料版本及用户勾选项，逐项回读后才显示核验成功。真实宿主必须继续调用既有审批与业务服务，不能直接修改队列或把这些传输记录当作正式审批。

接口、接入边界和逐项验收见 [宿主接口说明](../docs/react-console-host-interface.md)。共享传输类型从 `src/jobagent/schemas/console_host.py` 生成：

```powershell
python scripts/build_console_host_contracts.py
python scripts/build_console_host_contracts.py --check
```

二级页面的发送只读态、单岗执行入口、集中已选清单、可读附件版本、过期待办与滚动恢复，详见 [二级页面核验记录](../docs/react-secondary-pages-verification-2026-11-02.md)。这些交互通过合成验收，真实宿主接入仍需实测。
