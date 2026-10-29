# Muse 知识核心与后段观察交付说明

本页保留知识核心的职责映射，并按现行pipeline协议更新活动口径。历史提交和私有审计不重写；旧跟踪记录在候选人authority切换后供只读追溯，当前宿主执行见 [pipeline飞轮](pipeline-flywheel.md)。代码提供接口和校验，实际网页、任务、通知及私有数据切换仍由宿主执行。

## 可复用能力

| 能力 | 类型与实现 |
|---|---|
| JD原文和发现归因 | schemas/jd_snapshot.py、jobs/jd_snapshot.py、storage/jd_snapshot_repository.py |
| 原文特征/因子化 | schemas/lexicon.py、jobs/jd_features.py、jobs/jd_factorization.py |
| 私有词库与组合 | jobs/lexicon.py、jobs/search_learning.py、jobs/query_derivation.py、storage/intake_strategy.py |
| 本人信号 | schemas/search_learning.py；L1原话私有追加，L2从来源重算 |
| 人工加岗与恢复 | schemas/job_intake.py、storage/job_intake_service.py、cli/job_intake.py |
| 后段权威与表单 | schemas/pipeline.py、jobs/pipeline.py、storage/pipeline_repository.py；统一pipeline_job_form |
| 通用迁移/产物同步 | schemas/pipeline_migration.py、schemas/pipeline_sync.py及对应storage服务 |
| 累计飞轮 | schemas/pipeline_metrics.py、jobs/pipeline_metrics.py、jobs/pipeline_diagnosis.py、storage/pipeline_metrics.py |
| 本人规则与复核 | schemas/pipeline_rules.py、storage/pipeline_rules.py；复用私有message_rule_*账本 |

## 前段知识边界

原始采集在归一化前保留；完整快照须有真实抓取时间和身份，实际搜索填真实query_hit，手工/推荐可以NULL，不能伪造查询。相同内容可保留不同发现，正文或元数据变化追加版本，原文不覆盖。列表要点保持listing/partial，不能拼为全文。

模型特征须有准确原文位置、别名依据和否定/必需性，失败退回有据结果；引文定位不代表语义判断已获本人确认。私人种子、域、基础查询、硬条件和候选人材料由宿主分别配置，不把维护者行业或文风当默认。

文案Accept不推断喜欢岗位；明确岗位兴趣、文案反馈和人工选择元数据分开。重复消息、同岗多入口和重复回执不增加独立样本；原始事件与派生摘要可回查。不把薪资/地点/文案拒绝降格为整个行业负偏好。

寻源默认conservative预算保持3查询/20详情尝试/每日50；支持显式扩展档，必须传profile和完整参数。计划本身不增额，实际读取先reserve再result，失败和重复占额；来源会话、间隔和风控继续有效。薪资比较显式upper_bound，底线与币种来自本人私有配置，未知或不可比REVIEW。

## 后段当前态与48小时政策

pipeline_jobs使用固定九态，只有带目标证据的允许转移可以更新状态、原因和时间，并原子追加历史。统一pipeline_job_form展示职位、薪资、JD、拟稿、实际发送、定制简历、入库和当前态，不再拼多套当前状态。

新状态权威启用后旧tracking不接受修改、不再生成到期检查。静默截止点只由真实sent_at、read_at、最后实质回复或定制简历发送中较晚时间加48小时产生；观察次数不决定废止。宿主必须先读真实已加载对话再提交no_reply。无精确时间/无验证证明保持proof_pending，不能靠导入时间建立时钟。已面试不自动无回复废止；终态不复活，新联系需独立轮次、本人请求和新批准。

已读、回复、索要简历、邀约与完成面试要有来源证据；角标只能疑似。回读不一致拒绝并暂停匹配目标；登录/风控停止该站并由本人处理，不重发、不换账号绕行。pipeline只引用既有outreach/conversations/applications批准、实际审计与准确回读，不改发送、租约或证据确认语义。

## 迁移与私有数据

原始行数、ID序列、声明、字段映射、优先级、入库时间依据和个人硬条件只在私有配置。离线migrate先备份原库与源字节，在临时库验证身份/完整性后原子激活。缺URL/身份保留intake，旧摘要保持NULL全文；卡片决定不冒充岗位终态。历史发送声明可保留greeting_sent/proof_pending，但准确sent_*仍NULL，不能假装已经通过原发送门禁。

verify/project逐行对账并回读；回滚仅在没有后续事实、当前与备份摘要一致时允许。已有新观察、批准或规则后不能用旧队列覆盖数据库。代码与数据版本要固定，运行指纹变更后新运行或显式迁移，不绕验证；不启动本地bridge、监听或浏览器控制链。

同一私有库保存快照、发现、因子化、词库版本、intake、pipeline、累计指标和本人规则。公开提交只含代码、协议、脱敏合成示例与代码测试证据，不包含真实JD、候选人资料、已发全文、招聘方消息或私人批次统计。

## 累计诊断与本人确认

先metrics得到原metric IDs，再diagnose。七维scope来自实际来源，NULL表示未知，不当通配符；CONTENT_仅内容版本，不当共享harness。historical_rate、sliced_cumulative_rate、optimized_rate分别核算闭合累计窗口，window_rate只参考；零分母NULL，废止仍留分母，不重复累计、不跨轮次借转化。

诊断只比累计比率、相邻累计窗口持续性、伴随漏斗与排除证据，不设绝对样本数触发门槛。缺证据和边界抖动保留持续观察，不把未核实原因算成正文或简历问题。诊断提案、准确scope/前后效果、本人rule_confirm、下一窗口复核分别追加；优化无效只给回滚提案，未经本人确认不生效。普通文案diff的成熟度另行校验，不能用它的样本门槛限制后段累计诊断。

## 宿主验收

按 [工程协议](pipeline-flywheel.md) 的通用切换检查与两轮模板，由Muse在本人授权后私有执行真实对账、完整JD、单实例恢复、页面登录、通知送达及规则复核。查询归因只统计真实搜索发现，人工/推荐单列，不为凑完整率补query_hit。

本工程没有改写运行中的Muse任务、访问招聘网站、发送招聘消息、创建任务或送达通知。真实迁移、切换和两轮结果保持unverified，real_browser_verified=false。代码pytest/Ruff/strict mypy/diff检查另留实际日志，合成通过不替代宿主真实验收。
