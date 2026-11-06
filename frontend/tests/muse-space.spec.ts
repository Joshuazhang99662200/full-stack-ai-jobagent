import { test, expect, type Page } from "@playwright/test";
import demo from "../src/demo.json" with { type: "json" };

async function open(page: Page) {
  await page.goto("/?demo=1");
  await page.locator(".muse-space [aria-label='岗位列表']").waitFor();
}

async function openDetail(page: Page, title: string) {
  await page
    .getByRole("button", { name: new RegExp(`^打开岗位详情：${title}`) })
    .click();
  await page.getByRole("dialog").waitFor();
}

const FORBIDDEN = [
  "不再复核",
  "直接执行已选队列",
  "先放一放",
  "signal",
  "宿主",
  "仅作参考",
  "读回",
  "审批并",
  "沟通记录：还没有",
  "接受原稿",
  "这版文案可以",
  "帮我改一下",
];

async function expectCleanCopy(page: Page) {
  const text = await page.locator("body").innerText();
  for (const phrase of FORBIDDEN) expect(text, phrase).not.toContain(phrase);
  expect(text).not.toMatch(/#\d{3,}/);
  expect(text).not.toMatch(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/);
  expect(text).not.toContain("。。");
}

test("the merged frame is the default and keeps the approval-only selection rule", async ({
  page,
}) => {
  await open(page);
  const surface = page.locator(".muse-space");
  await expect(surface.getByRole("tab", { name: "切换到任务进度" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(surface.locator("[aria-label='岗位列表']")).toContainText("选择");
  await expect(surface.getByLabel("选择队列与一键投递")).toContainText(
    "只执行已批准的岗位",
  );
  await expect(surface.getByRole("button", { name: /一键投递，已选 0 个岗位/ })).toBeDisabled();
  await expectCleanCopy(page);
  for (const tab of ["运行记录", "沟通进展", "数据说明"]) {
    await surface.getByRole("tab", { name: `切换到${tab}` }).click();
    await expectCleanCopy(page);
  }
});

test("approving a greeting never sends it; sending is a separate confirmation", async ({
  page,
}) => {
  await open(page);
  await openDetail(page, "数据工程师");
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "批准并发送" }).click();
  await dialog.getByRole("button", { name: "批准这份材料" }).click();
  await expect(dialog).toContainText("这份材料已批准，还没有发送");
  await dialog.getByRole("button", { name: "继续到确认发送" }).click();
  await expect(dialog.getByRole("button", { name: "确认发送" })).toBeEnabled();
  await expect(dialog).not.toContainText("已发送：");
  await expectCleanCopy(page);
});

test("an edited draft must be approved again before it can be sent", async ({
  page,
}) => {
  await open(page);
  await openDetail(page, "数据工程师");
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "批准并发送" }).click();
  await dialog.getByRole("button", { name: "批准这份材料" }).click();
  await dialog.getByRole("button", { name: "继续到确认发送" }).click();
  await dialog
    .getByRole("textbox", { name: "招呼语（拟发送，可编辑）" })
    .fill("您好，这是改过的合成招呼语。");
  await expect(dialog).toContainText("正文改过了，需要重新批准后才能发送。");
  await expect(dialog.getByRole("button", { name: "批准这份招呼语" })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "确认发送" })).toHaveCount(0);
});

test("missing conversation records stay unknown and history copy is plain", async ({
  page,
}) => {
  await open(page);
  await openDetail(page, "数据工程师");
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "查看材料与历史" }).click();
  await expect(dialog).toContainText("沟通原文未保存，对方是否回复尚未核实。");
  await expect(dialog).toContainText("历版招呼语");
  await expectCleanCopy(page);
});

test("the execution list names blocked jobs instead of internal numbers", async ({
  page,
}) => {
  await open(page);
  await page.getByRole("button", { name: "生成执行清单" }).click();
  const dialog = page.getByRole("dialog", { name: "执行清单" });
  await expect(dialog).toContainText("执行清单是空的。");
  await expect(dialog).toContainText("以下岗位这次不执行");
  await expect(dialog).toContainText("合成机构");
  await expectCleanCopy(page);
});

test("the default frame fits a phone screen without sideways scrolling", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
});

test("a read-only real source keeps counts unknown and disables writes", async ({
  page,
}) => {
  await page.route("**/api/snapshot", (route) => route.fulfill({ json: demo }));
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText("待办来源读取未完成");
  await expect(page.getByRole("tab", { name: /^等你处理/ })).toContainText("?");
  await expect(page.getByRole("button", { name: "生成执行清单" })).toBeDisabled();
  await openDetail(page, "数据工程师");
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("button", { name: "批准并发送" })).toBeDisabled();
  await expect(dialog.getByRole("status")).toContainText("保存服务尚未接入");
});

test("an unavailable real source is diagnosed without falling back to the demo", async ({
  page,
}) => {
  await page.route("**/api/snapshot", (route) =>
    route.fulfill({ status: 503, body: "unavailable" }),
  );
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText("来源尚未接通");
  await expect(
    page.getByText("合成演示 · 不访问真实招聘渠道", { exact: true }),
  ).toHaveCount(0);
});
