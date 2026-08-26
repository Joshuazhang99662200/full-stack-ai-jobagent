# resume-builder 研究笔记

[StoneLL1/resume-builder](https://github.com/StoneLL1/resume-builder) · MIT · Agent Skill(SKILL.md + references/)· 可在 Claude Code / Codex / OpenClaw / Hermes 上运行。

本项目把它作为**默认渲染器与写作方法论来源**,不作为改写器。接入方式与职责切分见 [rendering-ats.md](../rendering-ats.md)。

## 它带来什么

本项目此前完全缺失的能力:

- **XeLaTeX 单页编译**,成功判据明确(日志含 `Output written on resume.pdf (1 page)`)
- **中文模板选型**:6 套,源自 `dyweb/awesome-resume-for-chinese`,并给出 ATS 场景下优先单栏无表格无照片的建议
- **写作手艺**:量化公式、STAR / 场景化五步法、关键数据加粗、动词开头、每条 ≤ 2 行、经历排序优先级(实习 > 项目 = 科研 > 校园)、交付前检查清单
- **超页处理**:先收紧间距或砍经历,**不缩字号**——与本项目"超出必须先删减而不是缩字号"一致

## 与本项目重合但口径不同的部分

它的 `claim-map` 四态与本项目的校验四态**不是同一个轴**,不可互相替代:

| | 轴 | 四态 |
|---|---|---|
| resume-builder `claim-map` | 这条信息**有没有出处** | 已确认 / 待确认 / 缺失阻塞 / 已省略 |
| 本项目 `VerificationStatus` | 写出的句子**是否被所引证据蕴含** | SUPPORTED / PARTIALLY_SUPPORTED / UNSUPPORTED / CONTRADICTED |

前者约等于 Candidate Core 的证据确认状态,本项目已用 `EVID_*` + 页码溯源 + SQLite 类型化承载,粒度更细。后者**它没有**,必须仍在本项目一侧执行。

## 采信边界

- 它的 `SKILL.md` 与 `references/` 是**参考资料**,不内联进本项目的运行时指令;运行时指令仍按 [prompt-routing.md](../optimizer/prompt-routing.md) 从本项目策略文档组装
- 交给它渲染的必须是**已通过本项目校验**的变体
- 它的「重包装」口径略松、「引导给数字」会制造出数字压力;冲突时一律以 [evidence-policy.md](../evidence-policy.md) 与 [quality-gates.md](../optimizer/quality-gates.md) 为准,**没有数字就留白**
- 它自带的 PDF 解析与信息收集流程不使用,本项目由 `candidate ingest` 承担
- 它会 `git clone` 模板仓库到工作区;模板仓库各有自己的许可证,分发本项目产物时需分别核对
- 复制其兼容素材时保留 MIT notice 与署名

## 风险

模板来自第三方合集,上游模板仓库的可用性与许可证独立于本项目。XeLaTeX 工具链需要本机安装,不是纯 Python 依赖。
