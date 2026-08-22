# 证据策略

每一条实质性主张都必须引用一个或多个 `EVID_*` 标识符。保全来源、置信度、确认状态、时序、归属、范围与指标含义。

允许的改写包括:忠实转述、压缩、重排、翻译、强调、省略,以及不扩大语义的合并。

不得凭空造出指标、不得把参与拔高为主导、不得把概念性认知说成生产经验、不得把推断出来的证据表述为事实。证据缺失时返回 `MISSING_EVIDENCE`,并可提出一个面试问题。

## Candidate Core 的强制约束

- 简历推理的输出必须是一个合法的 `CandidateDraft`,绑定同一个 Candidate ID 与确切的 `RESUME_*:page:N` 来源。
- 若提供方的响应携带 `user_confirmed=true`、不同的 Candidate ID、不同的 Resume ID,或指向不存在的页码,则属于非法的提供方输出。
- `CandidateEvidenceService.add_draft` 拒绝接收已预先标记为确认的输入。
- `CandidateEvidenceService.confirm` 是 Candidate Core 中唯一能把可采信证据提升为已确认状态的操作;弱证据会被拒绝。
- 用户编辑会把溯源改为 `user_edit`,保留原 Evidence ID,并把该条目退回未确认状态。
- 面试答案的溯源为 `interview` 且保持未确认。被跳过的问题不产生任何 EvidenceItem。

本地 SQLite 仓库存放私密的运行记录,但日志与 CLI 错误信息不得回显简历正文或提供方的原始载荷。
