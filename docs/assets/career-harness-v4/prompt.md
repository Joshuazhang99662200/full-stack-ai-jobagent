# 暖色主图生成提示词

使用内置 imagegen 工具生成。用户附图仅作为手绘风格参考；上一版总图作为流程内容参考。未复制附图中的品牌或产品架构。

```text
Use case: infographic-diagram / style-transfer.
Create a polished, legible Chinese hand-drawn workflow infographic for the open-source repository CareerHarness. This is a NEW sibling illustration redesign of the existing workflow, NOT a screenshot of a product UI.
INPUT ROLES:
Image 1 is STYLE REFERENCE ONLY: the user's warm cream hand-drawn architecture infographic. Take the friendly illustrated linework, off-white paper, small mint/ochre/peach icons, brown ink, restrained highlight hierarchy. Do not copy its Claude Code title, brand logos or architecture content.
Image 2 is CONTENT REFERENCE ONLY: the current blue CareerHarness workflow. Preserve its evidence grounding, human approval, material branches, true readback and bounded feedback loop. Do not preserve its blue background, heavy boxes or blueprint visual style.

OUTPUT: One high-resolution illustration, broad landscape 4:3-ish composition, approximately 1600 x 1200 or larger. Flat clean warm ivory paper (#FAF7EF approximate), fine irregular brown/charcoal pen outlines, subtly rounded hand-drawn panels. Gentle mint green for facts, muted peach and pale yellow for human decisions. A small coherent set of simple hand-drawn icons (resume page, person, browser, evidence book, chat bubble, magnifier, documents, checkmark, paper plane, receipt, funnel, loop). No emojis, mascots, decorative sparkles, gradients, shadows, dark panels, brand logos, faux app chrome or dense code. Typography: exceptionally clear, large neat Chinese handwritten-print labels, not cursive. Lots of breathing room. This should look like the supplied warm reference, NOT like a corporate slide full of identical cards, and NOT like text in a screenshot.

VISUAL STRUCTURE:
Title at top left: “CareerHarness”
Main Chinese title beside or below it: “AI 求职工作流”
Use FIVE low broad horizontal zones with small side labels. Connect the zones logically with actual visible arrow lines; do not run lines through words or icons. The page's warm highlight is the human approval step. Keep arrows directional and the reply/resume alternatives visibly branched, never imply every greeting immediately sends a resume.

Zone 1 side label “协同准备”
Three or four icon-labelled steps:
“资料与目标” (small sublabel “简历、经历、硬条件”)
→ “渠道选择” (small sublabel “浏览器 / MCP，预检 JD 补齐”)
→ “本人确认事实” (small sublabel “编号列表，可确认一组”)
→ a mint book “已确认证据” (small sublabel “保留原文与页码”).
Show a discreet mint dependency line from this evidence book supporting the matching and material preparation below, labelled “共用事实来源”. This is a dependency, not an extra approval.

Zone 2 side label “岗位与对话”
Two entry icons grouped together, labelled “先读已有对话” and “再找新岗位”, converge into
“完整 JD” → “匹配与筛选”.
Sublabel below matching: “硬条件、证据、缺口与风险”.
Keep the order: restore conversations and open items before supplementing with new jobs. No fabricated job data.

Zone 3 side label “材料准备”
A visibly branching route for the TWO material alternatives:
upper chat bubble “招呼 / 回复” → “独立复核”
lower document “定向简历” → “复核与成品检查”.
The lower route has a small but readable condition annotation: “索取简历或本人决定推进”.
Both routes converge to the following human approval zone. Do NOT depict the greeting flowing automatically into sending a resume.

Zone 4 side label “确认与执行”
A person with approval stamp “本人逐项审批”, emphasised with a warm pale amber wash and slightly stronger ochre outline. Sublabel “准确全文 + 实际附件”.
→ shield/check icon “发送前核验”
→ paper plane “执行 / 人工交接”
→ receipt icon “回读与记账”.
A small short return arrow beside this approval step annotated “内容改变，重新审批”. Main execution line must stay uninterrupted.

Zone 5 side label “运营与改进”
Funnel icon “观察转化” (small sublabel “已读不回 / 简历后约面”)
→ analysis icon “诊断与提案”
→ person/check icon “本人确认规则”
→ small loop/check “复核后续效果”.
Draw one clear return arrow from the final step back to Zone 2, labelled “进入下一轮”.
Do not invent percentages, counts, charts, dashboards or claims about observed outcomes. These labels describe what is tracked, not measured values.

Footer, readable and unobtrusive:
“流程示意；具体能力与版本见 README。”

All quoted Chinese labels must be spelled correctly. Prefer these short labels to additional prose. No extra invented feature names. Do not include the reference image's Claude Code components, hook names, SDKs, tool lists or service brands. Make it friendly, warm, simple and easy to scan, with visually distinctive icons rather than long paragraphs.
```


## 页脚文字调整

按用户要求删除主图左下角长句，保留右下角流程示意说明，其余图文保持。使用内置 imagegen 编辑；手机版同步修改可编辑源。
