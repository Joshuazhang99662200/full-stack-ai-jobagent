# React 控制台依赖

核验于 2026-10-31。界面与时间轴为本项目原创实现，不复制 affectUI Pro、后台模板或其他项目的界面源码。

| 依赖 | 锁定版本 | 许可证 | 使用方式 |
|---|---|---|---|
| React / react-dom | 19.3.1 | MIT | React 组件与浏览器渲染运行时 |
| scheduler | 0.28.0 | MIT | react-dom 的传递运行时依赖 |
| Vite | 8.3.5 | MIT | 本地开发和构建工具 |
| TypeScript | 7.0.2 | Apache-2.0 | 类型检查与声明生成 |

版本、完整性摘要和传递依赖以 `frontend/package-lock.json` 为准。许可证从 npm 包元数据及随包 LICENSE 核验；上游为 [React](https://github.com/facebook/react)、[Vite](https://github.com/vitejs/vite)、[TypeScript](https://github.com/microsoft/TypeScript)。浏览器测试和审核工具仅属开发依赖，不进入业务执行链。

保留运行时 MIT notices。Apache-2.0 的本项目代码不改变上游依赖各自许可证。发布自行构建的资产时应一并分发 `frontend/THIRD_PARTY_NOTICES.md`。React 库输出将 React 声明为外部依赖，宿主仍需安装兼容版本。

依赖不会修改候选人事实、审批门禁或投递权限。禁止把公共合成示例替换为真实私有数据后提交。
