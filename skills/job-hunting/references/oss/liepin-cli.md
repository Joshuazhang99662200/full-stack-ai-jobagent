# liepin-cli 研究笔记

猎聘官方系的本地 CLI，用用户自行粘贴的 `x-user-token` 授权（授权页由 `liepin-cli auth open` 打开），`--output json` 输出结构化结果，请求前按本仓库自带 JSON Schema 校验。

只把它当作**不透明的进程边界**：本项目未内联其任何源码，它也没有声明许可证，因此除进程调用外不可复用。`LiepinCliJobSource` 只调用只读的 `job search`。

`job apply` 属于投递表面，必须留在独立的投递连接器边界内，配独立授权与审批门禁；Job Intelligence 不得 import 或调用它。

token 过期、401/403、风控与验证码一律翻译为 `USER_INTERVENTION_REQUIRED` 交还给人，不自动重试、不更换账号。授权流程本身需要可交互终端，智能体不能代为完成。
