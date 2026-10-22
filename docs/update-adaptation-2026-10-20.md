# 2026-10-20 更新核对与初步适配

## 已确认范围

对照仓库、前次项目 memory 和当前 CLI，先补齐 evals、在线简历审批及信箱规则的运行与文档衔接。保留已有未提交实现，不操作平台或生产数据库，不提交或推送。

## 核对依据与差异

- 当前提交 `d2442f8` 已记录 Harness、独立复核、外联、对话、巡检和前端桥接；10 月 15–16 日 memory 中“全部未提交”的描述已过时。
- Codex memory 索引仍只有初始化记录。本次前次沟通依据来自 Claude 的本项目 memory，重点为 10 月 20 日在线简历规则和信箱交接；memory 内容经现有实现核对后用于适配。
- 工作区已有 P0 更新：平台可观测性、已读/送达回执、检索词命中留存及迁移 0010；检查期间又加入规则版本摘要、招呼策略标签、回复重写记录和在线简历只读快照/版本查询。实现文件仍有变化，因此最终门禁只证明当次检查的工作区状态。
- 完整 evals 设计已定；P1–P4 尚未提供可执行入口。P0 已有 HarnessVersion 与 ProfileSnapshot 等埋点契约，平台在线简历仍只读，快照/版本查询不代表上线流程可执行。
- 信箱 CLI 已支持直接调用；只读检查返回无待处理来件。接手不覆盖其他执行会话身份，转达不自动产生审批或发送。

前次沟通来源为本机 Claude 项目目录下的 `memory/liepin-online-resume-read-only.md`（10 月 20 日）、`memory/cowork-mailbox.md`（10 月 20 日）、`memory/pipeline-build-status.md` 和 `memory/platform-send-behavior.md`（10 月 16 日）。平台行为只作为历史观测，本次未访问招聘网站；发生差异时以当前页面、来源清单和停止条件为准。

## 操作清单

- [x] 检查提交、工作区、项目 memory、schema 与能力目录。
- [x] 复现 `patrol receipts` 漏登记导致的能力目录门禁失败。
- [x] 对齐入口、来源说明、巡检、检索词与前端信箱文档；新增可打包的评测边界说明。
- [x] 清理当前检查器报告的导入顺序及长行格式问题。
- [x] 跑完整测试、Ruff、mypy 与 diff 检查。
- [x] 在 `dist/` 构建独立 Codex 验证包，检查完整性与命令可用性。

## 验证方法

默认临时目录在本次 Windows 沙箱内不可写。使用已存在且被忽略的 `.pytest_cache/` 作为测试临时目录父路径，避免把临时文件纳入版本控制：

```powershell
python -m pytest -q --basetemp=.pytest_cache/adaptation-gate-20261020
python -m ruff check .
python -m mypy src/jobagent
git diff --check
```

`--basetemp` 会清理指定目录；为每次独立验证选择新的专用子目录，不指向用户数据。首次完整诊断运行在能力目录断言处停止，结果为 656 passed、1 failed；缺少的命令为 `patrol receipts`。

## 最终验证结果

- 全量测试：**712 passed，104.81 秒**；Ruff 通过；mypy 检查 117 个源码文件通过；`git diff --check` 通过，仅提示已有文件的 LF/CRLF 转换。
- 此前两轮运行遇到正在写入的版本模块或 profile 命令未加载，结果不作为最终门禁。最终运行前后 280 个源码、技能与测试文件的聚合 SHA-256 一致：`e0f443aa2c7a221d484df79e65d206c1e06a805bfb54aad3b8612985df7d8d64`。
- 独立 Codex 包：`dist/codex-adaptation-verified-20261020/job-hunting.zip`。完整性为 ok，缺失依赖为空；186 个打包文件与源文件逐一核对一致。新评测规则和 profile runtime 均在清单中。
- 使用包内 bootstrap 在 `dist/` 隔离空库验证 `patrol receipts` 与 `profile versions`，均成功；未访问生产库或平台。
- 包尚未替换全局安装。浏览器、调度器和渲染器仍需宿主探测；本次验证不代表已启用巡检或对外发送。

本次改动集中在说明与兼容衔接，业务模块保留原有及并行加入的实现，仅修正明确的格式问题。未改变人工审批、证据确认或投递门禁；未写 memory、提交或推送。
