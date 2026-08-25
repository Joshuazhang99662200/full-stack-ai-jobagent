# 猎聘 listing 寻源

## 它给什么、不给什么

猎聘的 `/mcp/search-job` **不返回 JD 正文**。一条结果只有:

`jobId` · `jobName` · `company` · `location` · `salary` · `education` · `workYears` · `industry` · `companyTags` · `companySize` · `financingStage` · `jobDetailUrl`

这不是缺陷,是该接口的设计意图:它面向「检索即投递」,不假设你会读 JD。

因此猎聘实现 `JobListingSource` 而非 `JobDiscoverySource`,产出 `JobListing` 而非 `SourceJobRecord`。两个端口刻意分开,让「没有 JD」在类型层面无法被绕过。

```powershell
jobagent jobs listings "AI Agent 产品负责人" --location 上海
```

`jobs search --source liepin` 会被显式拒绝并指向本命令。

## 绝不做的事

**绝不用摘要字段合成 `jd_raw`。** 把 `education`、`workYears`、`industry`、`companyTags` 拼成一段文本冒充 JD,会让下游的需求抽取、证据映射与可解释匹配全部建立在编造的文本上。这正是本项目最反对的静默降级。缺 JD 就是缺 JD,说出来,交给人补。

`liepin-cli` 的 `job apply` 与 `resume` 写入子命令(`update-*`、`add-*`)**不接入**:投递属于独立边界,候选人的在线简历保持只读。改写只产出附件简历,不回写平台档案。`resume get` 只读,可用于接地。

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
