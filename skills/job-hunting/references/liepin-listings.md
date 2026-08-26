# 猎聘 listing 寻源

## 它给什么、不给什么

猎聘的 `/mcp/search-job` **不返回 JD 正文**。一条结果只有:

`jobId` · `jobName` · `company` · `location` · `salary` · `education` · `workYears` · `industry` · `companyTags` · `companySize` · `financingStage` · `jobDetailUrl`

这不是缺陷,是该接口的设计意图:它面向「检索即投递」,不假设你会读 JD。

结果里还带一个「直招 / 猎头」标记,键名是 `jobType` 或 `jobKind`(取值有 int 也有 str),映射进 `JobListing.job_kind` 并**原样保留**。上游明确要求 `--job-kind` 与搜索结果一致、不得凭感觉填写,所以它只能从搜索结果里带出来:缺失就是 `None`,绝不补默认值,也绝不从公司名或招聘方类型反推。

因此猎聘实现 `JobListingSource` 而非 `JobDiscoverySource`,产出 `JobListing` 而非 `SourceJobRecord`。两个端口刻意分开,让「没有 JD」在类型层面无法被绕过。

```powershell
jobagent jobs listings "AI Agent 产品负责人" --location 上海
```

`jobs search --source liepin` 会被显式拒绝并指向本命令。

## 绝不做的事

**绝不用摘要字段合成 `jd_raw`。** 把 `education`、`workYears`、`industry`、`companyTags` 拼成一段文本冒充 JD,会让下游的需求抽取、证据映射与可解释匹配全部建立在编造的文本上。这正是本项目最反对的静默降级。缺 JD 就是缺 JD,说出来,交给人补。

`liepin-cli` 的 `resume` 写入子命令(`update-*`、`add-*`)**不接入**:候选人的在线简历保持只读,改写只产出附件简历,不回写平台档案。`resume get` 只读,可用于接地。

`job apply` **已接入,但只在投递边界内**:它由 `LiepinCliDeliverySource` 调用,而该连接器只能被 `DeliveryGate` 在重新校验人工审批之后触达。寻源侧永远够不到它——投递连接器与寻源连接器分开注册,一个平台可读从不意味着可以向它提交。投递时必须回填搜索结果给出的 `job_kind`,取不到就拒绝投递,不在 1 与 2 之间猜。

## listing 能做什么

listing 足以驱动**发现与确定性硬过滤**:`salary`、`workYears`、`education`、`industry`、`location` 都是硬过滤字段。

年限门槛尤其有用——它常常在读 JD 之前就把职位判死。先用它收窄候选集,再让人只为真正够得着的职位去取 JD。

listing **不足以**驱动匹配、改写或投递包。那些一律需要完整 JD。

## 工作流衔接

1. `jobs suggest-queries` 从已确认证据推导检索词
2. `jobs listings` 按词取回真实职位,跨词去重
3. 用 listing 字段做硬过滤与排序,收窄到少数目标
4. **由人**从 `jobDetailUrl` 取回 JD 正文
5. 有了 JD 才进入 `jobs requirements` → `filter` → `match` → 优化器

第 4 步没有自动化。不要为了跑通流程去抓详情页:那需要登录态,会触碰风控与反爬边界。

## 招聘方类型:本项目唯一被允许影响产物的推断属性

详情页的招聘方卡片会给出姓名与所属机构,猎聘还会**自己标注「猎头」**。据此可以判定对面是猎头还是用人单位内部。

这是本项目第一个**未经证据接地却被允许影响产物**的属性,因此它必须始终带着置信度与产生它的信号一起流转,路由**只能门控在置信度上**,不能直接信任标签:

| 情形 | 类型 | 置信度 | 可否硬路由 |
|---|---|---|---|
| 平台明确写「猎头」 | `headhunter` | 0.95 | 可以 |
| 头衔含 HR / 人力资源 / 招聘 | `hr` | 0.8 | 可以 |
| 头衔含 总监 / 负责人 / CTO | `hiring_manager` | 0.8 | 可以 |
| 机构名与用人单位一致 | `internal_unspecified` | 0.6 | **不可以** |
| 机构名与用人单位不一致 | `headhunter` | 0.6 | **不可以** |
| 无任何信号 | `unknown` | 0.0 | **不可以** |

`internal_unspecified` **是一个真实答案,不是占位符**。卡片能证明对方是用人单位一方,但通常证明不了他是 HR 还是用人经理;把它折叠成一个猜测,等于在一个虚构的区分上路由整份简历改写。宁可回退到通用策略。

只有平台**自己标注**的才算「已陈述」。机构名里出现「人才咨询」「顾问」只是推断,不得借用已陈述那一档的置信度。

低于阈值时回退通用策略,不猜、也不静默调低阈值。

## 停止条件

| 触发 | 处理 |
|---|---|
| `liepin-cli` 不在 PATH | `USER_INTERVENTION_REQUIRED`;由人安装 |
| 退出码 2 | `USER_INTERVENTION_REQUIRED`;非交互下上游**不打印任何提示**,一律按需授权处理,提示跑 `liepin-cli setup` |
| 退出码 1 且含 401/403/token/登录/风控 | `USER_INTERVENTION_REQUIRED`;不重试、不换号 |
| 退出码 1 其余情形 | `INVALID_PROVIDER_OUTPUT`;传输失败,不伪装成需人工介入 |
| 输出非合法 JSON 或缺必填字段 | `INVALID_PROVIDER_OUTPUT` |

授权由用户在**可交互终端**用 `liepin-cli setup` 粘贴猎聘官方 `x-user-token` 完成。智能体不代为完成,也不经手 token 值。token 有效期 90 天。

## 实现注记

上游在 stdout 为管道时按 Windows ANSI 代码页(cp936/GBK)输出,而非 UTF-8;连接器自行解码(utf-8 → gb18030 回退),否则中文会整片变成 `U+FFFD`。

上游仓库名是 `liepin-cil`(其自身拼写),命令与包名是 `liepin-cli`。它**未声明许可证**,因此除子进程调用外不得复用其代码。复用边界见 [oss/liepin-cli.md](oss/liepin-cli.md) 与 [oss/source-manifest.yaml](oss/source-manifest.yaml)。
