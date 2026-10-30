# JD 快照、词库与已发送跟踪契约

基准38afd89，接续已通过844项测试的寻源修订。用户要求继续更新并最终创建一个PR，授权分批提交及推送功能分支；不合并main。本说明是附件评审后的实施契约。

## 与附件的修订差异

- 沿用已确认的岗位/文案反馈拆分、薪资重叠规则和3查询/20详情/每日<=50预算，不重新引入approve=喜欢岗位、词频+1或8–12查询。
- 快照内容版本与搜索发现记录分开；query_hit只在搜索来源必填，手动/推荐来源如实标记。源文本按原样哈希，不能使用归一化后的JD冒充原文。
- 六维分类保留。hard带必需/优先、否定信息；negative来自私有用户政策，不作为全局行业事实。模型只提供有原文位置的候选，未知词先观察。
- count统计独立岗位的最新完整快照，不按重复抓取或批准增加。人工权重与派生软偏好分开；MD是政策输入，统计和版本保留来源。
- 新跟踪独立读取既有批准与sent审计，再核对宿主提交的准确回读；record本身不验证浏览器正文，不声称可认证真实网页或操作者。
- 未确认未读计数不算回复；异常事件保留原状态并暂停自动检查，须本人明确恢复。14天与4次有效检查同时满足才过期；漏查补查至少间隔一天，不能一轮连查4次制造过期。

## 六项契约

1. JDSnapshotInput / JDSnapshot：job_id、job_url、platform、fetched_at、query_hit、title、company、location、salary_raw、jd_text、completeness及observation_id/discovery_kind。存储计算jd_text_hash、content_digest、snapshot_version、snapshot_id。观测ID同文幂等、异文拒绝；同内容新发现不增加内容版本，内容恢复到旧稿仍是新版本，历史保留。历史采集早于当前版本且内容不同则拒绝，不悄悄回滚。
2. JDFeature / JDFeatureSet：固定六维，原文evidence与字符start/end、polarity、requirement_level、canonical term；绑定快照ID、版本和JD哈希。列表/不完整不抽取。规则先跑，模型格式/证据/别名/维度错误时回退并给稳定错误码，不日志输出全文。
3. Lexicon：YAML头与六维Markdown词项、组合模板；必需版本/域/日期/统计来源字段。词含count、last_seen、source、可选aliases/weight/seed与来源引用；人工seed需作者与轮次。解析和序列化是纯文本函数，文件I/O在CLI。词频不影响偏好权重；以重算的独立岗位统计决定观察成熟度。
4. CombinationPlan：扩展SearchQueryDeriver，按2–4个概念组件组合；正向查询只用domain/scenario/tech/role；hard/negative不直接拼查询。有限候选数、确定性次序、冷却回访、探索和基线回退，最多本轮query_limit（默认3、上限6）。三条独立公司与岗位的明确方向拒绝才后移对应实际查询，不删除；普通薪资/文案拒绝不迁移为方向信号。
5. LexiconRebuild：消费现有SearchLearningRequest的显式岗位偏好；文案与招聘方结果不改变权重。绝对重算，旧ID不改consumed；同输入重跑版本不变，来源摘要改变才增加版本；旧MD版本存私有库，可读取旧版本回滚，不删除事件。
6. SentTracking：保留附件12状态枚举。approved_pending_execution/leased是既有门禁的执行前投影，不创建已发记录。初始sent和awaiting_reply写两条历史。创建必须关联已批准且审计结果sent的准确条目和一致回读。状态变更CAS、事件ID幂等、观察证据不可重复计检查。终态原因先写事件再closed归档，不能复活；新联系须新的批准/审计/跟踪ID。replied后的新等待必须关联既有对话批准及sent回执并再次精确回读，不接受任意JSON声称获批。

## 日程与事件

无回复检查按发出后1、3、7、14天。只在next_check_at到期时可记一次真实无回复检查；补查不加速。观察期满14天且检查>=4后写no_response_expired和closed。replied/screening/interview转后续人工对话，不自动改变巡检频率。疑似回复不推进状态。job_closed需要详情/列表证据；本人放弃需原话与来源。异常暂停不改业务状态、不重发。

screening/interview和无回复/拒绝仅进评估报告。负面观察至少三个不同已发岗位才呈现模式，仍不自动改词库或候选人证据。关闭后无next_check_at、due报告排除。

## 分层与发布

所有Pydantic定义放schemas；jobs领域不导入SQLite/Typer/浏览器；存储追加迁移和历史；CLI只组装验证输入与引用。不修改outreach/application批准、租约、发送、审计语义，不新增自动发送/回复动作。真实数据仅私有数据库/文件；测试使用合成样本。源读取与模型由Muse提供，真实宿主仍须验收。
