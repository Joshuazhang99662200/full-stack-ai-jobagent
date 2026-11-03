import { test, expect } from "@playwright/test";

test("Muse source controls and detail layout replace the reinterpreted console", async ({
  page,
}) => {
  await page.goto("/?demo=1&template=zip");
  await expect(
    page.getByRole("tab", { name: "切换到数据说明", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("group", { name: "排序方式" })).toBeVisible();
  await page.getByRole("button", { name: /打开岗位详情：数据工程师/ }).click();
  const modal = page.getByRole("dialog", { name: /数据工程师/ });
  await expect(
    modal.getByRole("region", { name: "职位要求", exact: true }),
  ).toBeVisible();
  await expect(
    modal.getByRole("region", { name: "进展", exact: true }),
  ).toBeVisible();
  await expect(
    modal.getByRole("region", { name: "招呼语", exact: true }),
  ).toBeVisible();
  await expect(modal.getByRole("tab", { name: "进展与操作" })).toHaveCount(0);
  await expect(
    modal.getByRole("button", { name: "查看材料与历史", exact: true }),
  ).toBeVisible();
});

test("Muse review uses JD, keywords, original body and saved-decision screen", async ({
  page,
}) => {
  await page.goto("/?demo=1&template=zip");
  await page.getByRole("button", { name: /数据工程师.*看看招呼语/ }).click();
  const modal = page.getByRole("dialog", { name: /数据工程师/ });
  await expect(
    modal.getByRole("heading", { name: "JD 要点", exact: true }),
  ).toBeVisible();
  await modal
    .getByRole("button", { name: "这版文案可以", exact: true })
    .click();
  await expect(modal.getByText("记下了。", { exact: true })).toBeVisible();
  await expect(
    modal.getByRole("button", { name: "继续到确认发送" }),
  ).toHaveCount(0);
});
