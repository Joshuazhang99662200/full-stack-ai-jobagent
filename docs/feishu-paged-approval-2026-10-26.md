# 飞书原生逐岗位审批与寻源反馈

本轮采用原生 Card 2.0 的“上一条／下一条”按钮，不包含手势滑动面板。卡片每次展示一个岗位，翻页保存当前招呼草稿；翻页不构成批准或负反馈。

## 接口

```python
from jobagent.bridge.feishu_approval import send_question_card

message_id = send_question_card(
    database, batch, ask, sender,
    candidate_id=candidate_id,
    query_strategy_version=current_strategy_version,
)
```

`batch` 和 `ask` 必须已经通过既有外联流程存储。`sender` 沿用现有飞书机器人发送器。必须提供对应候选人 ID 才读取其已存匹配分、理由和缺口；未提供或未评估时如实显示未评估，不猜测候选人或匹配百分数。薪资和地点来自职位存储，JD 要点来自需求抽取。

回调继续通过 `feishu_approval.listen` / `handle_card_event`。新版状态在 `paged_card_states`；未注册新版状态的旧卡继续使用旧处理器。常驻 Python 监听器已经加载旧模块时，需要在空闲窗口进行一次受控重启才会加载新代码；新增模块不会让既有进程自动热更新。

新卡引用候选人证据时必须传对应 `candidate_id`；每次批准从当前事实库重新读取仍为本人确认的证据，而非相信旧卡中的证据 ID。证据已撤回、职位变化或最新匹配已落入不允许起草档位时拒绝批准。

常规 `auto_push` 和 `notify feishu` 从本机 `feishu_push.json` 的显式 `candidate_id` 配置透传到 `send_cards` 与新卡状态；不会根据飞书接收人或旧条目猜候选人。缺少配置时，新卡显示“未绑定候选人”、禁用真实批准，伪造按钮回调也不能批准；浏览、编辑、回绝及明确的演示模式仍可用。配置仅影响之后发出的新卡，不会把已经发出的未绑定卡静默变成可执行审批，需重新发出绑定明确的新卡。

批准按钮只处理当前岗位提交的最终全文，沿用 `OutreachService.build_batch / ask / approve` 创建单项子批次；发送仍需既有 worker、租约及发送回执。原问题不会被整批批准。本人身份、事件去重、页面版本、24 小时卡片时效、原问题摘要、职位内容变化及已联系状态均须通过检查。所有条目决定后，原问题撤回，子批次的有效批准保留。

回绝写为独立决定，不创建发送授权、发送失败或“从未联系”的记录。可选原因分为岗位不喜欢、薪资、地点、产品方向、职责级别、文案、事实、暂时不处理及其他。反馈与批准、当前页版本在同一 SQLite 事务中提交。

## 合成数据交互演示

`send_question_card(..., demo_mode=True)` 对从零构造并明确标注的合成岗位启用同一原生界面。醒目标题为“演示 · 无发送权”；翻页、输入和演示决定可通过真实飞书回调验证，决定和说明只存 `paged_card_states`，不会创建 `OutreachApproval`、子批次、worker 待发或真实寻源负反馈。演示不能被当成真实投递验收。

这套卡片仅对应首条招呼，不批准定向简历或 `ApplicationPackage`。简历成品通知可发静态原生卡配套附件，但真正简历投递审批继续走既有 applications 门禁；当前没有简历原生审批回调桥，不能把首条招呼卡片的批准挪作简历授权。

## 下一次显式采集前消费反馈

```python
from jobagent.bridge.sourcing_feedback import next_fetch_strategy

plan = next_fetch_strategy(
    database, source, current_query_order,
    previous_version=current_strategy_version,
)
```

返回 `FeedbackSearchStrategy`，并将版本与解释写入 `sourcing_feedback_strategies`。协调器把 `ordered_queries` 与 `deprioritized_job_ids` 作为下一次交给执行器的寻源策略输入；`generator_feedback_ids` 单独给文案生成器，`collection_feedback_ids` 给采集质量处理。此函数不访问平台、不启动轮询，不会自行唤醒执行器。

约束：

- 单次岗位不喜欢只降低该岗位优先级，不排除行业、公司或检索词。
- 同一检索词至少有三个不同岗位被明确标记“不喜欢产品方向”并附说明，才将该词后移；检索词不会被删除。
- 文案问题和事实问题不改变检索词或岗位偏好。
- 后续明确批准同一岗位可覆盖此前该岗位的负偏好；旧事件仍完整保留。
- 搜索计划不会改变硬筛选条件、候选人事实、审批、发送额度或工具许可。

## 验证范围

已编写合成数据测试覆盖翻页草稿留存、编辑后单项批准、回绝隔离、本人校验、重放、旧页面操作、卡片过期、职位变更、父问题关闭及显式采集前策略消费。真实飞书送达、客户端展示、事件回调和新进程加载仍须在实际联调中验收；本文件不将离线测试等同于平台实测。
