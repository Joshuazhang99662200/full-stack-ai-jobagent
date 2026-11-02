import { test, expect } from "@playwright/test";

test("a mismatched before-text signal never becomes a verified regeneration", async ({
  page,
}) => {
  await page.goto("/tests/fixtures/muse-sync-host.html?corrupt=1");
  await page.getByRole("tab", { name: /^全部/ }).click();
  await page
    .getByRole("button", { name: "查看详情：数据工程师", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await dialog
    .getByRole("button", { name: "重新生成招呼语", exact: true })
    .click();
  await page.evaluate(() => {
    (window as any).syncFixture.resume();
  });
  await expect(dialog.getByRole("alert")).toContainText(
    "改前/改后记录尚未核实",
  );
  await expect(
    dialog.getByRole("button", { name: "批准并发送", exact: true }),
  ).toBeDisabled();
});

test("injected regeneration preserves full history, blocks concurrent edits and invalidates old approval", async ({
  page,
}) => {
  await page.goto("/tests/fixtures/muse-sync-host.html");
  await page.getByRole("tab", { name: /^全部/ }).click();
  await page
    .getByRole("button", { name: "查看详情：数据工程师", exact: true })
    .click();
  const dialog = page.getByRole("dialog"),
    text = dialog.getByRole("textbox", {
      name: "招呼稿（可编辑）",
      exact: true,
    });
  const before = await text.inputValue();
  await dialog
    .getByRole("button", { name: "重新生成招呼语", exact: true })
    .click();
  await expect(text).toBeDisabled();
  await page.evaluate(() => {
    (window as any).syncFixture.resume();
  });
  await expect(text).toHaveValue(before + " 合成宿主生成的新版全文。");
  await dialog.getByText("查看材料与历史", { exact: true }).click();
  await dialog
    .getByRole("region", { name: "招呼语改写记录" })
    .getByText(/AI 重新生成/)
    .click();
  await expect(
    dialog.getByRole("region", { name: "招呼语改写记录" }),
  ).toContainText(before);
  const state = await page.evaluate(
    async () => await (window as any).syncFixture.state(),
  );
  expect(state.jobs[0].materials).toHaveLength(2);
  expect(
    state.jobs[0].events.filter((e: any) => e.kind === "approve_material"),
  ).toHaveLength(1);
  expect(state.batches).toHaveLength(0);
  const approvalNode = dialog
    .getByRole("list", { name: "工作流程" })
    .getByText("材料批准", { exact: true })
    .locator("..")
    .locator("span")
    .first();
  await expect(approvalNode).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
});

test("quick execution excludes unapproved selection and shows its reason in that job's progress", async ({
  page,
}) => {
  await page.goto("/?demo=1");
  await page
    .getByRole("checkbox", { name: "选择岗位：数据工程师", exact: true })
    .click();
  await expect(
    page.getByRole("checkbox", { name: "选择岗位：数据工程师", exact: true }),
  ).toBeChecked();
  await page.getByRole("button", { name: /^一键投递/ }).click();
  await expect(page.locator(".trow[data-open] .prog").first()).toContainText(
    "尚未获批准",
  );
  await expect(
    page.getByRole("region", { name: "选择队列与一键投递" }),
  ).toContainText("拦下 1 条");
  await page.reload();
  await expect(
    page.getByRole("checkbox", { name: "选择岗位：数据工程师", exact: true }),
  ).toBeChecked();
});

test("shared channel badges use the supplied brand palette in list and detail", async ({
  page,
}) => {
  await page.goto("/?demo=1");
  const badge = page.locator('.muse-current [data-channel="BOSS"]').first();
  await expect(badge).toHaveCSS("background-color", "rgb(0, 168, 160)");
  await expect(badge).toHaveCSS("color", "rgb(255, 255, 255)");
  await page
    .getByRole("button", { name: "查看详情：数据工程师", exact: true })
    .click();
  await expect(
    page.getByRole("dialog").locator('[data-channel="BOSS"]').first(),
  ).toHaveCSS("background-color", "rgb(0, 168, 160)");
});

test("selection survives reload and inversion is scoped to visible jobs", async ({
  page,
}) => {
  await page.goto("/?demo=1");
  const bar = page.getByRole("region", { name: "选择队列与一键投递" });
  await bar.getByRole("button", { name: "全选当前列表", exact: true }).click();
  await expect(bar).toContainText("已选 1 个岗位");
  await page.reload();
  await expect(bar).toContainText("已选 1 个岗位");
  await bar.getByRole("button", { name: "反选当前列表", exact: true }).click();
  await expect(bar).toContainText("已选 0 个岗位");
});

test("regeneration is a distinct unavailable capability without a host AI service", async ({
  page,
}) => {
  await page.goto("/?demo=1");
  await page
    .getByRole("button", { name: "查看详情：数据工程师", exact: true })
    .click();
  await expect(
    page
      .getByRole("dialog")
      .getByRole("button", { name: "重新生成招呼语", exact: true }),
  ).toBeDisabled();
  await expect(page.getByRole("dialog")).toContainText("重新生成服务尚未接入");
});
