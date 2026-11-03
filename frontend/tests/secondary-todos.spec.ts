import { test, expect, seed, storageKey } from "./secondaryFixtures";
import demo from "../src/demo.json" with { type: "json" };
test("stale personal decisions remain visible and cannot answer an old material", async ({
  page,
}) => {
  await seed(page);
  await page.evaluate((key) => {
    const value = JSON.parse(localStorage.getItem(key)!);
    value.state.todos[0].status = "pending";
    value.state.todos[0].material_revision = "OLD_SYNTHETIC_REVISION";
    localStorage.setItem(key, JSON.stringify(value));
  }, storageKey);
  await page.reload();
  await expect(page.locator(".jq-attention")).toHaveCount(1);
  await page.locator(".jq-attention").click();
  await expect(page.getByRole("dialog")).toContainText(
    "材料已变化，请重新审阅新版",
  );
  await expect(
    page.getByRole("button", { name: "暂缓推进", exact: true }),
  ).toBeDisabled();
});
