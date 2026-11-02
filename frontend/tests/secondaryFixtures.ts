import { test as base, expect, type Page } from "@playwright/test";
export { expect };
export const storageKey = "ja-console.synthetic.v1.CAND_DEMO";
export const test = base.extend<{ freshPanel: void }>({
  freshPanel: [
    async ({ page }, use) => {
      await page.goto("/?demo=1");
      await page.evaluate(() => localStorage.clear());
      await page.reload();
      await expect(page.locator(".jq-row")).toHaveCount(5);
      await use();
    },
    { auto: true },
  ],
});
export async function seed(page: Page) {
  await page.getByRole("button", { name: "数据工程师", exact: true }).click();
  await page.getByRole("button", { name: "批准这份材料", exact: true }).click();
  await expect(page.getByRole("status").last()).toContainText("已保存");
  await page.getByRole("button", { name: "关闭详情" }).click();
}
