# React 面板交互实施计划

目标：在现有 React 组件上实现已确认设计及差异清单，使用同一路径接入只读快照、宿主与合成数据。

架构：Python schema 是新宿主协议的类型权威，脚本生成 TypeScript 类型；前端数据源与交互服务通过依赖注入连接。合成持久化服务只在明确 demo 模式启用，真实 HTTP 查询继续只读。

技术：现有 Python / Pydantic、TypeScript / React、Vite、Playwright；不新增依赖。

共同约束：保留现有样式与原有未提交修改；不读取真实候选人数据；不提交、推送或发布；决定不触发执行，未知不重试，缺少回读不认定发送。

按本会话内顺序执行，不使用子智能体，不增加提交检查点。

## 任务 1：权威协议与可替换数据源

文件：`src/jobagent/schemas/console_host.py`、`scripts/build_console_host_contracts.py`、`frontend/src/hostContracts.ts`、`frontend/src/dataSource.ts`、`tests/console/test_host_contracts.py`、`frontend/tests/host-service.spec.ts`。

- [x] 先写协议与生成一致性测试，运行并确认缺少模型导致失败。
- [x] 定义材料、决定、待办、回读、批次、登录请求、同步结果与宿主投影，不重新定义领域模型。
- [x] 实现类型生成与快照 / HTTP 适配器，保留来源错误及候选人隔离。
- [x] 运行 `python -m pytest tests/console/test_host_contracts.py -q` 与前端协议测试。

接口方向：`ConsoleDataSource` 提供读列表、详情、材料、待办、渠道、批次及定义；写能力为显式可选方法。只读适配器不提供写方法。

## 任务 2：可持久化的合成宿主服务

文件：`frontend/src/demoHost.ts`、`frontend/src/hostService.ts`、`frontend/tests/host-service.spec.ts`。

- [x] 先写失败用例：同键同内容只保存一次，同键不同内容拒绝；未知只核验；版本失效不清待办。
- [x] 实现追加事件、单写手、操作结果查询和材料版本绑定；存储接口以 `load` / `save` 注入。
- [x] 先写批次选择与无回读用例，再实现前置检查、选择绑定、执行与逐条回读演示。
- [x] 先写同步、登录恢复与旧历史保存用例，再实现对应的独立服务；不启动宿主任务或浏览器。
- [x] 运行前端服务测试；复用 demo 存储后重新创建服务，验证会话恢复一致。

验收示例：

```ts
const first = await source.recordDecision(request);
const replay = await source.recordDecision(request);
expect(replay).toEqual(first);
expect((await source.getHostState()).jobs[0].events).toHaveLength(1);
```

## 任务 3：React 交互接入

文件：`frontend/src/SourceConsole.tsx`、`frontend/src/HostControls.tsx`、`frontend/src/DecisionPanel.tsx`、`frontend/src/ExecutionDialog.tsx`、`frontend/src/TodoPanel.tsx`、`frontend/src/main.tsx`、`frontend/src/Console.tsx`、`frontend/src/JobQueue.tsx`、`frontend/src/JobDetailTabs.tsx`、`frontend/src/styles.css`、`frontend/tests/host-ui.spec.ts`。

- [x] 先写浏览器失败用例：决定保存后重载一致、仅决定无执行、红点阅读不消失、关闭返回焦点。
- [x] 新增数据容器与宿主上下文，旧 `Console snapshot=...` 继续工作。
- [x] 接入准确材料、决定编辑、待办、执行清单、登录状态及同步结果；未知状态仅查询，未接入明确禁用。
- [x] 增加更多 / 排查路径，历史保留可读全文与可打开材料；默认界面不展示内部字段。
- [x] 运行 `npm.cmd test -- tests/host-ui.spec.ts`，确认对应行为通过。

## 任务 4：清单共有行为与兼容性

文件：`frontend/src/JobQueue.tsx`、`frontend/src/JobDetailTabs.tsx`、`frontend/src/styles.css`、`frontend/tests/console.spec.ts`、`frontend/tests/host-ui.spec.ts`。

- [x] 先补整行、选中文本、渠道弹窗、排序、五列、薪资与原始信息隔离的失败测试。
- [x] 实现匹配理由优先、排序保持及结束沉底；红点计数只读取明确个人待办。
- [x] 验证 320–1920px、键盘、旧渠道路由、既有 workflow 与 SSR；旧测试如触及主动变更的文案，按真实新行为更新。

## 任务 5：交付核验

- [x] 更新 `frontend/README.md` 和新增宿主协议说明，逐项列出验收与实际接入边界。
- [x] `npm.cmd run typecheck`、`npm.cmd run build`、`npm.cmd run test:ssr`、`npm.cmd test`。
- [x] `python -m pytest -q`、`python -m ruff check .`、`python -m mypy src/jobagent`、`git diff --check`。
- [x] 检查最终 diff，确认没有真实数据、依赖、审批弱化或对原有工作区修改的覆盖。

## 最终验证结果

- Python 全套：1819 passed。使用仓库忽略的私有临时目录；沙箱外运行以允许本机 HTTP 测试。
- 前端全套：52 passed；随后待办红点样式修正对应的 10 项交互测试再次通过。
- TypeScript / 生产构建 / 库构建 / SSR smoke：通过。
- Ruff、mypy（245 个源文件）、生成类型一致性和 git diff --check：通过。
- 桌面和手机合成截图已检查；未读取真实记录、未执行真实外部动作、未提交或推送。

## PR 发布范围

实施验证完成后，本人于 2026-11-02 在聊天中明确要求“推1次PR”。本 PR 仅发布 React 面板改造；原工作区其他未提交的宿主文档和记忆功能改动不在本 PR 内。
