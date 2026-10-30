# README V2 图片源

## 工作链路图

`workflow.png`、`resume-exchange.png`、`feedback.png` 将[修订后的流程底稿](../../workflow-outline.md)分别绘成整体链路、简历交换决策和投后运营闭环。三张图都有 `-mobile.png` 单列版本。它们是工作流说明图，沿用 Console 的 token 与字体，不是产品界面、平台截图或真实效果数据。实现范围见[流程实现说明](../../workflow-implementation.md)。

修改 `workflow.html` 和 `workflow.css` 后，按下方相同环境运行 `node docs/assets/career-harness-v2/render-workflow.mjs` 重新生成。`workflow-manifest.json` 记录底稿、源码与六张导出图片的 SHA-256。渲染禁止 HTTP 请求，不读取账号或候选人资料。

## 原有程序输出图

三组 PNG 是本目录 HTML/CSS 对实际合成输出的排版截图，没有绘制浏览器、终端窗口或产品网页。图片中的程序字段、摘要和结果来自 `samples.json`，不是文案设计时填入的指标。每组各有 1280px 桌面排版和 375px 手机单列排版，均以 2 倍像素密度导出，README 用 `<picture>` 在 600px 以下切换。

## 材料来源

| 材料 | 复用方式 | 来源与许可证 |
|---|---|---|
| Console 的配色 token、字体分工与细线表格 | token 直接复用并调整 CJK fallback 与图片字级；规则参考 | [Hallmark V2 Console](https://github.com/Nutlope/hallmark/blob/8f6969f8922caabde9de1784959eae11ddf68073/skills/hallmark/references/themes/console.md)，MIT，保留在 `HALLMARK-LICENSE.txt` |
| Host Grotesk | 仅用于文档图片排版，随源文件分发 | [Google Fonts](https://github.com/google/fonts/tree/main/ofl/hostgrotesk)，SIL OFL 1.1，见 `fonts/HostGrotesk-OFL.txt` |
| Atkinson Hyperlegible Mono | 仅用于代码、ID 与摘要 | [Google Fonts](https://github.com/google/fonts/tree/main/ofl/atkinsonhyperlegiblemono)，SIL OFL 1.1，见 `fonts/AtkinsonHyperlegibleMono-OFL.txt` |
| 中文字形 | 使用本机 Microsoft YaHei 的回退排版 | 不复制或分发系统字体文件 |
| JD、证据、diff、复核与摘要 | 本仓库合成夹具的实际执行输出 | 文件来源及内容摘要保留在 `samples.json`，不含真实求职资料 |

Console 的官方样图仅供研究，没有复制进项目。没有使用第三方照片、品牌标识或用户评价。

## 输出边界

复核结果由单元测试的结构化夹具提供，图片展示的是校验行为，不证明发生过一次真实模型独立复核。审批答复同样是合成夹具，不能作为真实发送授权。数据捕获过程中没有调用招聘平台。

`figures.html` 是可直接打开的静态排版源，不依赖脚本显示内容。`render.mjs` 从 `samples.json` 生成它，再用无账号浏览器截图；HTTP 请求会被阻止。渲染工具使用 Puppeteer Core 和本机 Chromium，需要 Node.js。工具依赖只放在文档构建环境，不进入 Python 包。

```powershell
# 安装到自选的文档工具目录，保留锁文件
npm install --prefix <文档工具目录> puppeteer-core@25.16.0 --ignore-scripts
$env:HALLMARK_PUPPETEER = "<文档工具目录>"
$env:CHROME_PATH = "<本机 Chromium 浏览器路径>"
node docs/assets/career-harness-v2/render.mjs
```

Hallmark 的机械检查针对 `figures.html` 和 CSS，以静态图片组件范围运行；不会把 GitHub 的 Markdown 容器计为本项目的网页，也不宣称 README 通过了网页转化率或首屏测试。

源码摘要按 UTF-8 文本统一为 LF 后计算，避免 Git 的 Windows 换行转换产生差异；图片输出摘要按原始文件字节计算。
