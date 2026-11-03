import { test, expect, seed, storageKey } from "./secondaryFixtures";
import demo from "../src/demo.json" with { type: "json" };
test("selection echo is complete, follows checked items and hides raw digests", async ({
  page,
}) => {
  await seed(page);
  await page.getByRole("button", { name: "执行清单", exact: true }).click();
  const echo = page.getByRole("region", { name: "已选清单核对" });
  await expect(echo).toContainText("尚未选择项目");
  await page.getByRole("checkbox", { name: /数据工程师/ }).check();
  await expect(echo).toContainText("数据工程师");
  await expect(echo).toContainText("初稿（合成）");
  await expect(echo).toContainText("您好，这是供审核的合成招呼语，尚未发送。");
  await expect(page.getByRole("dialog")).not.toContainText("sha256:");
  await page.getByRole("checkbox", { name: /数据工程师/ }).uncheck();
  await expect(echo).toContainText("尚未选择项目");
  await expect(
    page.getByRole("button", { name: "确认执行所选项目" }),
  ).toBeDisabled();
});
test("unverified status labels never masquerade as a positive readback", async ({
  page,
}) => {
  await seed(page);
  await page.getByRole("button", { name: "执行清单", exact: true }).click();
  await page.getByRole("button", { name: "关闭详情", exact: true }).click();
  await page.evaluate((key) => {
    const value = JSON.parse(localStorage.getItem(key)!);
    const batch = value.state.batches[0];
    batch.status = "unknown";
    batch.items[0].selected = true;
    batch.items[0].status = "verified";
    batch.items[0].readback = null;
    localStorage.setItem(key, JSON.stringify(value));
  }, storageKey);
  await page.reload();
  await page.getByRole("button", { name: "执行清单", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("结果未知，请先核验");
  await expect(page.getByText("合成回读已核验", { exact: true })).toHaveCount(
    0,
  );
});
test("selection and source limitations remain clear in a mobile execution dialog", async ({
  page,
}) => {
  await seed(page);
  await page.getByRole("button", { name: "执行清单", exact: true }).click();
  await page.setViewportSize({ width: 375, height: 850 });
  await page.getByRole("checkbox", { name: /数据工程师/ }).check();
  const modal = page.getByRole("dialog");
  await expect(modal).toContainText("交互设计师");
  const box = await modal.boundingBox();
  expect(box!.width + box!.x).toBeLessThanOrEqual(375);
  expect(await modal.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(
    true,
  );
  await page.screenshot({
    path: "../.jobagent/secondary-execution-mobile.png",
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({
    path: "../.jobagent/secondary-execution-desktop.png",
  });
});
