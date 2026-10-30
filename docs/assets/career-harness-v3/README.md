# Hallmark Blueprint 总链路图

这张图替换 README 的总链路图，其他配图及旧版素材继续保留。内容来自[流程底稿](../../workflow-outline.md)，实现范围见[流程实现说明](../../workflow-implementation.md)。

## 设计来源

使用本机 Hallmark V2.0.0。重新分发得到 Blueprint、Vantage、Grid，选择 Blueprint 的 cyanotype 纸张、单色线条和双层关键线；`tokens.css`、`base.css` 由官方 scaffold 生成。保留仓库已有的 Host Grotesk 本地字体及中文系统字体回退，许可证位于[原素材目录](../career-harness-v2/README.md)。Hallmark 许可证见本目录 `HALLMARK-LICENSE.txt`。

将上一版分栏长文改成实际连接的流程图：顶部的证据来源、已有对话与新岗位入口、材料分支、本人审批、执行回读、运营及规则复核。实线表示工作推进，虚线表示事实复用与重新核验。只有工作流数据，没有产品界面、转化率或平台回执。

## 重现

`workflow.html` 是无需脚本即可显示的排版源；`workflow.css` 控制桌面地图与手机单列图。使用已有文档工具环境：

```powershell
$env:HALLMARK_PUPPETEER = "<安装 puppeteer-core 的文档工具目录>"
$env:CHROME_PATH = "<本机 Chromium 浏览器路径>"
node docs/assets/career-harness-v3/render.mjs
```

渲染器禁止 HTTP 请求，不读取候选人资料或浏览器账号。生成桌面 1280px 和手机 375px 两种排版的 2 倍密度 PNG，并记录源码与图片摘要。README 用 `<picture>` 选择对应图片。
