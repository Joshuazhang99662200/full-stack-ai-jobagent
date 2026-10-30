---
lexicon_version: v1
domain: 待配置领域
updated_at: 2026-10-28
based_on_snapshots: 0
based_on_feedback_events: 0
---

# 私有词库空模板

复制到本人私有区后填写领域与词项。下方为空，附录示例不会被解析成活跃词项。
人工种子须 source=人工、seed=true，并填写 author 与 round_id。
不得把招聘方的岗位要求写成候选人事实。

## 域词 domain

## 场景词 scenario

## 技术词 tech

## 角色词 role

## 硬要求 hard

## 排除词 negative

## 组合模板 combinations

- {domain} {role}
- {domain} {scenario} {role}
- {scenario} {tech} {role}
- {domain} {tech} {role}

## 脱敏示例（仅供抄写格式）

```markdown
## 域词 domain
- 基金 | count: 0 | last_seen: null | source: 人工 | seed: true | author: synthetic-owner | round_id: INIT
## 角色词 role
- 产品经理 | count: 0 | last_seen: null | source: 人工 | seed: true | author: synthetic-owner | round_id: INIT
```

```markdown
## 域词 domain
- 品牌 | count: 0 | last_seen: null | source: 人工 | seed: true | author: synthetic-designer | round_id: INIT
## 角色词 role
- 设计师 | count: 0 | last_seen: null | source: 人工 | seed: true | author: synthetic-designer | round_id: INIT
```
