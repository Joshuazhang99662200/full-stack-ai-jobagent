# 轮询控制台

控制台提供可复用的 React 组件、本地只读页面，以及供宿主使用的同一份 JSON 查询。主视图按岗位组织任务队列，以公共真实时间轴显示同时进行的活动；轮次与 run_id 保留为追溯信息。它展示已有事实和明确上报的执行活动，不负责调度、生成、审批或发送。

## 岗位队列与并行活动

首列为岗位和公司。活动只根据明确的 job_id 与该候选人的岗位或可靠的 normalized_job_id 关联，不能把整轮活动猜成属于某个岗位。同一岗位跨运行的同时活动分别占用子行；不同岗位的相同时间点对齐，不把 fetch、起草、复核等画成全局串行步骤。

界面的近时窗口仅控制显示范围，不改变寻源预算或任务调度。窗口外记录和未归属岗位的活动保留在快照及运行追溯中，不能补造关联。

排序先把业务状态 abandoned 的岗位放在最后，再参考同一候选人最近已存的硬筛结果与匹配结果；通过硬筛、匹配较高的岗位优先。缺少评估明确显示未评估，不视为零分。旧评估保留时间、策略和输入摘要，仅供队列展示，不代表按当前配置重新评估。不同策略的分值应结合详情解读。

执行失败、取消运行、暂停或心跳过期不会自动关闭岗位。沉底只改变显示位置，不改写九态，不触发放弃、重开或发送。

## 三个维度

| 维度 | 来源 | 用途 |
|---|---|---|
| 运行状态 | HarnessRun.phase | 区分运行、等待本人、登录受阻、结果未知、结束 |
| 当前活动 | 宿主显式记录的活动事件 | 显示 fetch、详情、匹配、起草、复核、审批等待、回读、汇总 |
| 岗位九态 | PipelineJob 与 PipelineHistory | 显示岗位业务状态及有证据的转移 |

待审批不增加岗位业务状态。岗位可能在索取简历时等待某份材料审批。九态按实际历史高亮，不能按枚举顺序推断经过所有阶段。

## 宿主读取完整字段

从仓库根目录执行：

```powershell
jobagent console definitions
jobagent console list CAND_DEMO --database .jobagent/jobagent.sqlite3 --workspace .
```

`CAND_DEMO` 是合成标识，使用时替换为当前已确认的候选人 ID。definitions 提供 JSON Schema，包括原有岗位、元数据、历史和运行契约。list 返回这些完整业务字段，包括 JD、准确招呼语、版本、摘要、证据引用和产物引用；前端没有显示的字段也能从详情展开。凭证配置不属于此接口。

数据源状态必须和结果一起读取：complete 表示该来源已读取；missing、invalid、unsupported 表示缺失、无效或尚未接入。数组为空不能独立证明该来源成功或已遍历全部站点。读取不创建数据库、不迁移、不确认 worker 事件，也不取得运行租约。

## 本地页面与组件

首次准备需要 Python 项目环境及符合 frontend/package.json 要求的 Node.js。前端依赖锁定在 package-lock.json；构建后运行不需要 CDN 或外部字体。

```powershell
cd frontend
npm.cmd ci
npm.cmd run build
cd ..
jobagent console serve CAND_DEMO --database .jobagent/jobagent.sqlite3 --workspace . --assets frontend/dist --port 8765
```

浏览器访问 `http://127.0.0.1:8765`。真实视图读取同源 `/api/snapshot` 和 `/api/definitions`。页面及接口只读；服务只监听本机，拒绝跨来源请求和不匹配的 Host，不提供任意本地文件下载。

演示入口显式使用 `?demo=1`，并标注合成数据。真实请求失败时不会自动换成演示或显示成功零结果。不要把真实快照放入前端 public、构建目录或仓库。

独立页面通过“刷新记录”读取最新本地快照；当前没有后台自动刷新。嵌入组件的宿主可以自行管理快照更新频率，这不会改变实际巡检任务的调度频率或查询额度。修改 Python 契约后，运行 `python scripts/build_console_demo.py` 重新生成公开示例与 JSON Schema，再重建前端。

React 组件的导出和嵌入示例见 [frontend/README.md](../frontend/README.md)。宿主可调用相同 JSON 查询，再把快照作为组件输入；无需依赖本地 HTTP 服务。CLI 和本仓库 MCP 桥接的只读出口共用查询实现，宿主选择适合自身的接入方式。

MCP 桥接启动时可显式指定工作区，避免自定义数据库路径导致运行目录识别错误：

```powershell
python -m jobagent.bridge.mcp_server --database .jobagent/jobagent.sqlite3 --workspace .
```

对应只读工具是 `console_list`（传 candidate_id）和 `console_definitions`。修改桥接版本后，需要宿主重新加载工具目录；已连接的旧进程不会自动得到新工具。

## 记录阶段

阶段记录是宿主对正在执行活动的观察，不能提升为审批、发送、已读等业务事实。记录须绑定已存在且属于该候选人的 HarnessRun；涉及单个岗位时必须登记准确 job_id，跨岗位的采集活动可以不绑定并保留在未归属清单。运行已结束后不能继续宣称正在执行。

宿主在实际开始阶段时记录 started；仍在执行时记录 heartbeat；等待本人或外部条件时记录 waiting；真正结束后记录 completed 或 failed。每个事件具有独立 event_id，同一阶段沿用 activity_id。失败和等待保留恢复点、产物及证据引用；重放同一事件必须保持原内容。

把输入 JSON 保存到私有目录，再运行 `jobagent console event <私有输入文件> --workspace .`。下面是合成字段示例，run_id、候选人、编号及时间必须替换为当前真实观察；不得把示例当作过去已经发生的事实导入：

```json
{
  "event_id": "EVENT_DEMO_FETCH_START",
  "candidate_id": "CAND_DEMO",
  "run_id": "RUN_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
  "activity_id": "ACTIVITY_DEMO_FETCH",
  "activity": "fetch",
  "status": "started",
  "occurred_at": "2026-10-31T09:50:00+08:00",
  "owner": "synthetic-host",
  "checkpoint_reference": "PRIVATE_CHECKPOINT_DEMO"
}
```

同一 activity_id 的 owner、job_id 和 activity 不得更换；阶段结束后须使用新活动编号。recorded_at 由程序登记，宿主不能在输入中冒充登记时间。默认超过五分钟没有活动观察时，运行新鲜度显示 stale；这是界面可观测性的提示，不影响业务超时、查询额度、放弃策略或原任务调度。

开始时间缺失就显示“未记录”，不从完成事件倒推耗时。心跳过期显示“状态未确认”，等待本人不显示为持续计算。过去没有记录的运行可以显示已有状态，不能补造曾经检查、审批或发送的事实。

## 现有数据的范围

原有 pipeline 已提供完整岗位字段和九态历史，平台契约目前为 Boss、智联。Harness 已有运行状态和产物；旧 worker 事件主要是完成记录，不能还原每一步的开始时间。新阶段记录需要宿主按协议实际调用，单纯启动页面不会替宿主记录。

原有全局轮询与外联审批记录并非都绑定候选人和运行；没有可靠关联的来源会报告尚未接入，不能混入其他候选人的数据。审批仍通过既有逐项、绑定准确文本及附件的流程完成，控制台不授予操作权限。
