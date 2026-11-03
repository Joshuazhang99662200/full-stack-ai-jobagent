# React 控制台依赖

核验于 2026-10-31。原 Console 界面与时间轴为本项目原创实现；Muse 模板直接复用用户提供并明确要求还原的源码，不复制 affectUI Pro 源码。

| 依赖 | 锁定版本 | 许可证 | 使用方式 |
|---|---|---|---|
| React / react-dom | 19.3.1 | MIT | React 组件与浏览器渲染运行时 |
| scheduler | 0.28.0 | MIT | react-dom 的传递运行时依赖 |
| Vite | 8.3.5 | MIT | 本地开发和构建工具 |
| TypeScript | 7.0.2 | Apache-2.0 | 类型检查与声明生成 |

版本、完整性摘要和传递依赖以 `frontend/package-lock.json` 为准。许可证从 npm 包元数据及随包 LICENSE 核验；上游为 [React](https://github.com/facebook/react)、[Vite](https://github.com/vitejs/vite)、[TypeScript](https://github.com/microsoft/TypeScript)。浏览器测试和审核工具仅属开发依赖，不进入业务执行链。

保留运行时 MIT notices。Apache-2.0 的本项目代码不改变上游依赖各自许可证。发布自行构建的资产时应一并分发 `frontend/THIRD_PARTY_NOTICES.md`。React 库输出将 React 声明为外部依赖，宿主仍需安装兼容版本。

依赖不会修改候选人事实、审批门禁或投递权限。禁止把公共合成示例替换为真实私有数据后提交。


2026-11-02 Muse 模板新增依赖：`@tanstack/react-query` / `@tanstack/query-core` 5.105.1、`tailwindcss` / `@tailwindcss/vite` 4.3.3、`tailwindcss-safe-area` 1.3.0，均从本地安装包元数据及许可证文件核验为 MIT；准确传递版本以锁文件为准。React Query 为外部运行时依赖，Tailwind 及 safe-area 为样式构建依赖。许可证保留于 `frontend/THIRD_PARTY_NOTICES.md`。

Muse 用户源码的来源和摘要见 `frontend/src/muse/provenance.json`；这是用户明确要求复用的输入，不对其额外声称第三方开源许可证。原私有资产、SDK 和服务端数据库实现没有打包。


2026-11-03：用户另行提供同步 zip，默认模板合并其客户端增量和 RPC 展示声明。`ChannelTag` 品牌色表直接复用；未复制或执行私有 SQL/SDK/投递脚本。该包摘要见 `frontend/src/muse/provenance.json` 的 `sync_archive`，差异与审批兼容方案见 `docs/panel-sync-merge-2026-11-03.md`；许可依据仍为用户明确要求复用，不额外声称第三方开源许可。
