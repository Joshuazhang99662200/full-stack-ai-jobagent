# 暖色手绘工作流配图

## 当前主图

README 使用 `workflow.png`：保留原暖色主图的布局与风格，仅通过局部编辑删除本人指定的左下角页脚句子；手机版已同步删除。`workflow-original.png` 为未修改的独立备份。另行重生成的 `workflow-regenerated.png` 未用于 README。局部编辑提示词见 [footer-edit-prompt.md](footer-edit-prompt.md)。

README 在所有窗口宽度下均显示这张暖色手绘主图，点击图片可查看原图。`workflow-mobile.png` 仅作为独立的可选版本保留，不自动替换首页主图。

用户提供暖色手绘架构图作为风格参考，覆盖此前 Blueprint 的视觉方向。主图使用内置 imagegen 生成，采用暖白纸底、棕色线条、薄荷绿图标与橙黄色审批重点；不复制参考图的品牌或架构内容。完整提示词见 [prompt.md](prompt.md)。

流程来自[文字底稿](../../workflow-outline.md)与[实现范围](../../workflow-implementation.md)，图片属于流程说明，没有产品界面或真实转化数据。旧版素材保留在相邻目录。

手机版由 `mobile.html`、`mobile.css` 独立排版，使用原创的简单线条图标。它沿用暖色方向，保留事实确认、材料分支、简历触发条件、准确全文与附件审批、回读和规则效果复核。不是将桌面图直接缩小，也没有对生成的位图进行脚本修改。

使用原文档构建环境，设定 `HALLMARK_PUPPETEER` 和 `CHROME_PATH` 后运行 `node docs/assets/career-harness-v4/render-mobile.mjs`，生成 375px 单列排版的两倍密度图片。渲染器禁止 HTTP 请求，不读取候选人资料或账号。

当前采用原主图局部去字版与本地可编辑的手机版。不宣称生成位图通过网页 CSS 规则检查。

源码摘要按 UTF-8 文本统一为 LF 后计算，避免 Git 的 Windows 换行转换产生差异；图片输出摘要按原始文件字节计算。
