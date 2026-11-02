import { test, expect, seed, storageKey } from "./secondaryFixtures";
import demo from "../src/demo.json" with { type: "json" };
test("shell restores window scroll and opener without a write on close", async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 600 });
  const row = page.locator('.jq-row[data-job="DEMO_E"]');
  await row.scrollIntoViewIfNeeded();
  await row.focus();
  const position = await page.evaluate(() => window.scrollY);
  await page.keyboard.press("Enter");
  const before = await page.evaluate(
    (key) => localStorage.getItem(key),
    storageKey,
  );
  const writes: string[] = [];
  page.on("request", (r) => {
    if (!["GET", "HEAD"].includes(r.method())) writes.push(r.url());
  });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.keyboard.press("Escape");
  await expect(row).toBeFocused();
  expect(
    Math.abs((await page.evaluate(() => window.scrollY)) - position),
  ).toBeLessThan(2);
  expect(writes).toEqual([]);
  expect(
    await page.evaluate((key) => localStorage.getItem(key), storageKey),
  ).toBe(before);
});
