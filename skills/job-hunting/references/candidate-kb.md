# 候选人知识库

把候选人知识库视为唯一权威,把每一份简历视为它的一个投影。将档案事实、证据、偏好、约束、搜索策略与未知字段分开存放。

自适应面试每次只针对当前的一个缺口提问。按歧义度、证据薄弱程度、目标岗位相关性与预期信息增益对缺口排序。用户可以跳过;"未知"始终是一个合法状态。

答案生成草稿证据。只有显式确认或经用户确认的可采信证据,才能支撑最终简历中的实质性主张。

## 已落地的 Candidate Core 路由

组合工作流时,使用这些原子 Python 服务:

- `PdfResumeParser.parse` 抽取有序的 PDF 页面与一个 SHA-256 源摘要。
- `ReasoningCandidateDraftExtractor.extract` 以提示词 ID `candidate.extract_draft.v1` 请求 `CandidateDraft`,并重新校验候选人与页码溯源。
- `CandidateOnboardingService.ingest_resume` 依次执行解析、抽取,然后做一次事务性仓库写入。
- `GapDetector.detect` 从档案、证据、未知项与目标岗位推导出当前缺口。
- `AdaptiveInterview.next_question` 返回零个或一个问题,并尊重最近的缺口 ID。
- `AdaptiveInterview.record_answer` 返回 `InterviewOutcome`;回答会带出一条未确认的面试证据,而跳过只带出一个事件。
- `CandidateReadinessService.evaluate` 报告描述完整度与证据就绪度。

面向本地操作者的工作流,路由到 `jobagent candidate ingest`、`import-draft`、`question`、`answer`、`confirm` 与 `status`。这些命令输出 JSON,并通过 `--database` 使用 SQLite。

不要把 PDF 文本抽取当作事实解读。若没有配置生产级推理提供方,请改用经人工评审的 `CandidateDraft` JSON 导入,而不是用启发式规则生成主张。
