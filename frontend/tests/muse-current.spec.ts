import { test, expect } from "@playwright/test";
import demo from "../src/demo.json" with { type: "json" };

test("readonly Muse keeps personal counts unknown and disables unavailable writes", async ({
  page,
}) => {
  await page.route("**/api/snapshot", (route) => route.fulfill({ json: demo }));
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText("待办来源读取未完成");
  await expect(page.getByRole("tab", { name: /等你处理/ })).toContainText("?");
  await page.getByRole("tab", { name: /^全部/ }).click();
  await page
    .getByRole("button", { name: "查看详情：数据工程师", exact: true })
    .click();
  await expect(
    page
      .getByRole("dialog")
      .getByRole("button", { name: "批准并发送", exact: true }),
  ).toBeDisabled();
  await expect(page.getByRole("dialog").getByRole("status")).toContainText(
    "保存服务尚未接入",
  );
});

test("current Muse uses the live navigation, table widths and modal hierarchy", async ({
  page,
}) => {
  await page.goto("/?demo=1");
  const surface = page.locator(".muse-current");
  await expect(surface.locator(".topbar-in")).toBeVisible();
  await expect(surface.locator(".wrap")).toHaveCSS("max-width", "1280px");
  await expect(surface.locator(".trow.head")).toContainText("待你处理");
  await surface
    .getByRole("button", { name: "查看详情：数据工程师", exact: true })
    .click();
  const dialog = surface.getByRole("dialog");
  for (const heading of [
    "匹配情况",
    "进展",
    "岗位要点",
    "招呼稿（可编辑）",
    "工作记录",
  ])
    await expect(
      dialog.getByRole("heading", { name: heading, exact: true }),
    ).toBeVisible();
  await expect(
    dialog.getByRole("button", { name: "批准并发送", exact: true }),
  ).toBeVisible();
  await expect(dialog.getByRole("tab")).toHaveCount(0);
});

test("current Muse todo opens independently and saves approval without execution", async ({
  page,
}) => {
  await page.goto("/?demo=1");
  await page.locator(".muse-current .todo-btn").first().click();
  const modal = page.getByRole("dialog");
  await expect(
    modal.getByRole("heading", { name: "依据", exact: true }),
  ).toBeVisible();
  await modal.getByRole("button", { name: /^接受原文 / }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(
    page.getByRole("status").filter({ hasText: "已记录" }),
  ).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "执行清单", exact: true }).click();
  await expect(page.getByRole("dialog").locator(".exec-row")).not.toHaveCount(
    0,
  );
  await expect(
    page
      .getByRole("dialog")
      .getByRole("button", { name: "确认执行", exact: true }),
  ).toBeEnabled();
  await expect(
    page.getByRole("dialog").getByText("已执行", { exact: true }),
  ).toHaveCount(0);
});

test("current Muse secondary pages keep live table structure and explain counts", async ({
  page,
}) => {
  await page.goto("/?demo=1");
  await page.getByRole("tab", { name: "运行记录", exact: true }).click();
  await expect(page.locator(".cols-run.head")).toContainText("已完成的工作");
  await page.getByRole("tab", { name: "沟通进展", exact: true }).click();
  await expect(page.locator(".cols-comm.head")).toContainText("最新沟通");
  await page.getByRole("tab", { name: "数据说明", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "计数口径", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".muse-current .doc")).toContainText(
    "一个岗位有多个待办也只算一次",
  );
});

test("unavailable real source is diagnosed, without a silent demo fallback", async ({
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
