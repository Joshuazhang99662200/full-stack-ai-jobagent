# Hallmark 审核记录

审核日期：2026-10-30。范围为 README 中的五张图片及静态画廊组件。主题沿用用户已确认的 V4 暖色手绘主图，主图文件保持不变。

## 页面容器检查

使用本机 Hallmark V2.0.0，固定上游版本 `8f6969f8922caabde9de1784959eae11ddf68073`，对 `gallery.html`、`gallery.css`、`tokens.css` 执行：

```text
sloplint.mjs gallery.html gallery.css tokens.css --scope component --genre editorial --render --json
```

结果为 0 fails、0 reflex、0 warns，原始结果保存在 [lint.json](lint.json)。渲染覆盖 1280×800、1440×900、1920×1080 首屏，以及 1440 和 375 宽完整画廊。

该检查只覆盖 HTML/CSS 容器；PNG 内部的字形、颜色和流程含义另行进行视觉与事实核对，不能据此宣称像素内容通过了 CSS 规则。

## 独立视觉与事实复核

按 Hallmark `review-finish.md` 使用未参与制作的新上下文审阅者。先查看截图，再查看源图和合成数据；逐屏检查 1440 长截图，并检查其他桌面与手机截图。

初审结果为 `fix`，唯一待办是本目录链接的 `review.md`、`manifest.json` 尚未创建。补齐后独立审阅者再次确认两处链接有效，最终结果为 `ship`，无剩余审核发现。

独立审阅结论：

- 四张新图与锁定主图构成同一风格家族：暖白纸底、棕色线条、薄荷绿状态与橙黄色本人确认；无待修视觉问题。
- 箭头清楚，无文字遮挡或裁切。手机端阅读细节需要打开原图，所有图片入口均可点击。
- `EVID_A`、`RESUME_1:page:1`、两段文本差异、复核夹具结果与四组摘要前八位均与 [samples.json](../career-harness-v2/samples.json) 一致。
- 合成夹具说明清楚，没有将夹具结论表述为真实模型独立复核；准确全文、实际附件审批与运营规则确认的权限边界保持清楚；无虚构转化数字。

旧图对按平台、方向、薪资段与材料版本比较、关闭与拒绝单独记录写得更细；新版是概览，完整口径见[工作链路底稿](../../workflow-outline.md)、[实现说明](../../workflow-implementation.md)和[运营文档](../../pipeline-flywheel.md)。

## 集成核对

- README 的四张辅助图均引用 V5，桌面与手机使用同一文件，可点击查看原图；旧的深色和自动切换手机版不再引用。
- 在 1280、600、599、390、320 宽核对：五张图片全部解码成功，无横向溢出，主图链接与图片来源相同。
- 主图 SHA-256：`24c5a4e27a87aff119017afaa4ec57d88f6ee62efccaafc8488aa2e8052e5d76`，与本轮开始前一致。
- 全量测试：1282 passed；Ruff 通过；strict mypy 181 个源文件通过。

不应稀释：已锁定主图、准确全文和实际附件的本人审批、合成夹具说明，以及原图查看入口。
