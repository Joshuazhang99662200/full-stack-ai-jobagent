# 自己加一个职位来源

来源是**数据,不是代码**。加一个平台意味着放一份 YAML,不需要 fork,也不需要改这个包。

内置的猎聘、智联、LinkedIn、BOSS、前程无忧只是这份契约的**参考实现**,没有任何特权。

## 三步

1. 先按 [source-onboarding.md](source-onboarding.md) 的五档阶梯评估该平台,确定它属于哪一种 `kind`
2. 照下面的模板写一份 YAML,放进你自己的目录
3. 用 `--sources-dir` 指向它

```powershell
jobagent jobs listings "产品经理" --source my-board --sources-dir .\my-sources
```

## 四种 kind

| kind | 用于 | 必需段落 |
|---|---|---|
| `listing_cli` | 平台有官方 CLI,以子进程调用(阶梯第 1 档) | `listing` |
| `public_page` | JD 在公开的服务端渲染页面里(第 4 档) | `detail` |
| `gated` | 没有可正当自动接入的路径(第 5 档) | `gate` |
| `fixture` | 合成数据,离线开发用 | 无 |

`gated` 是一等公民。**把接不进来的平台如实建模,好过留一个静默的空洞**——链路保持完整,边界可见。

## 模板:公开页面

```yaml
schema_version: "1.0"
id: my-board
display_name: 示例招聘
kind: public_page
onboarding_tier: 4
notes: 走到第几档、为什么这么定,写在这里。
detail:
  # 按顺序尝试,第一个命中的标题作为 JD 起点
  start_headings: [职位描述, 岗位职责]
  # JD 在其后第一个出现的标题处截断
  stop_headings: [公司简介, 工作地址, 猜你喜欢]
  # 平台"藏起" JD 时的措辞;命中即停下交人,绝不保存半截 JD
  gate_markers: [登录查看, 安全验证]
  min_length: 30
```

`stop_headings` 是最容易被忽略、也最容易出事的一项。页面通常还带着公司简介、防诈提示和"猜你喜欢"推荐位;**不设边界,这些会混进 `jd_raw`**,让下游的需求抽取建立在一段被污染的文本上。

## 模板:官方 CLI

```yaml
schema_version: "1.0"
id: my-cli-board
display_name: 示例平台
kind: listing_cli
onboarding_tier: 1
listing:
  command: [my-board-cli, job, search, --output, json]
  query_options:          # JobSearchQuery 字段 -> 命令行参数
    query: --keyword
    location: --city
  envelope_keys: [data, list, records]   # 逐层解包,直到拿到列表
  field_map:              # 契约字段 -> 上游可能的键名,按顺序尝试
    source_job_id: [jobId, id]
    title: [jobName, title]
    company: [company, compName]
    url: [detailUrl, link]
    location: [city, address]
    salary_text: [salary]
  intervention_markers:   # 命中即 USER_INTERVENTION_REQUIRED,绝不重试
    - "401"
    - 登录
    - 验证码
    - 风控
```

`source_job_id`、`title`、`company`、`url` 四个字段**必须**映射,否则清单校验不通过——缺了它们的 listing 无法被识别,也无法回到原始职位。

## 模板:门控平台

```yaml
schema_version: "1.0"
id: walled-board
display_name: 某封闭平台
kind: gated
onboarding_tier: 5
gate:
  gate: waf_challenge
  detail: 详情接口返回 WAF 挑战,未登录不可达。
  manual_route: 在自己的浏览器打开职位,复制 JD,用 `jobagent jobs ingest-jd` 提交。
```

## 清单不能做什么

清单描述的是**如何读取**一个平台,它无法授予工作流本来没有的权限。契约里**不存在**表达以下内容的字段:

- 投递、提交、审批
- 凭据、Cookie、token 的存放或注入
- 重试策略、代理轮换、指纹伪装
- 绕过登录、验证码或风控

这不是靠自觉,是契约层面就没有这些字段;有测试锁住这一点。想接的平台需要上述任何一条才能取数,那它就是 `gated`。

## JD 正文永远不许合成

若某来源只给列表字段而不给 JD 正文(猎聘的搜索接口就是如此),那它产出 `JobListing` 而非 `SourceJobRecord`。

**绝不能**把 `education`、`work_years`、`industry` 之类的摘要字段拼成一段文本冒充 `jd_raw`。缺 JD 就是缺 JD,如实说出来,交给人补齐。两个端口在类型层面就是分开的,正是为了让这件事绕不过去。
