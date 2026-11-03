<!-- preference-memory-sha256: c77edc84988f01e7dd1a2a5abfcfcc51021dac47fb0c799e036684d8ebe5799e -->
# 候选人偏好 Memory

- 候选人：`CAND_TEST`
- 版本：`PMEM_ONE`
- 上一版：`无`
- 更新时间：2026-10-26T00:00:00+00:00
- 已消费事件：1

偏好仅影响选材、表达与岗位优先级，不确认事实或授予审批、发送权限。
正文与元数据一并校验；手工修改会停止程序回读，避免忽略本人改动。

## 岗位偏好 jobs

暂无已归纳规则。

## 招呼偏好 greetings

### RULE_ONE

- 偏好：Emphasize model evaluation.
- 范围：`role`；条件：Financial AI
- 当前 JD：`无指定岗位`
- 来源事件：EV_ONE
- 更新时间：2026-10-26T00:00:00+00:00

<!-- typed-preference-memory -->
```json
{
  "schema_version": "1.0",
  "candidate_id": "CAND_TEST",
  "version": "PMEM_ONE",
  "previous_version": null,
  "consumed_event_ids": [
    "EV_ONE"
  ],
  "rules": [
    {
      "schema_version": "1.0",
      "rule_id": "RULE_ONE",
      "category": "greetings",
      "scope": "role",
      "condition": "Financial AI",
      "job_id": null,
      "text": "Emphasize model evaluation.",
      "source_event_ids": [
        "EV_ONE"
      ],
      "updated_at": "2026-10-26T00:00:00Z"
    }
  ],
  "updated_at": "2026-10-26T00:00:00Z"
}
```
