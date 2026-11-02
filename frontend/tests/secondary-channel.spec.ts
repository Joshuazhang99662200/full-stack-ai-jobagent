import { test, expect, seed, storageKey } from "./secondaryFixtures";
import demo from "../src/demo.json" with { type: "json" };
test("readonly personal counts are unknown, and only dropped channels offer recovery", async ({
  page,
}) => {
  await seed(page);
  await page.evaluate((key) => {
    const value = JSON.parse(localStorage.getItem(key)!);
    value.state.channels.push({
      channel: "SYNTHETIC_UNKNOWN",
      label: "示例未知渠道",
      status: "unknown",
      checked_at: null,
      restore_requested_at: null,
    });
    localStorage.setItem(key, JSON.stringify(value));
  }, storageKey);
  await page.reload();
  const popups: string[] = [];
  page.on("popup", (p) => popups.push(p.url()));
  await page.getByRole("button", { name: "渠道状态", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "渠道状态", exact: true });
  await expect(
    dialog.getByText("已登录", { exact: true }).first(),
  ).toBeVisible();
  await expect(
    dialog.getByText("登录情况尚未确认", { exact: true }),
  ).toBeVisible();
  await expect(
    dialog.getByRole("button", { name: "请求恢复登录", exact: true }),
  ).toHaveCount(1);
  await dialog
    .getByRole("button", { name: "请求恢复登录", exact: true })
    .click();
  await expect(dialog.getByText("登录已掉线", { exact: true })).toBeVisible();
  await expect(
    dialog.getByRole("button", { name: "已请求恢复", exact: true }),
  ).toBeDisabled();
  expect(popups).toEqual([]);
  await page.route("**/api/snapshot", (r) => r.fulfill({ json: demo }));
  await page.route("**/api/definitions", (r) => r.fulfill({ json: {} }));
  await page.goto("/");
  const needs = page.locator('.jq-summary button[data-lane="needs"]');
  await expect(needs).toContainText("待确认");
  await expect(needs.locator(".jq-personal-badge")).toHaveCount(0);
});
test("workflow keeps failed and unconfirmed records distinct on the same step", async ({
  page,
}) => {
  const snapshot = structuredClone(demo),
    original = snapshot.runs[0].activities[0];
  snapshot.runs = [snapshot.runs[0]];
  snapshot.runs[0].freshness = "stale";
  snapshot.runs[0].activities = [
    {
      ...original,
      activity: "match",
      activity_id: "SYNTHETIC_FAILED",
      event_id: "SYNTHETIC_FAILED",
      status: "failed",
    },
    {
      ...original,
      activity: "match",
      activity_id: "SYNTHETIC_STALE",
      event_id: "SYNTHETIC_STALE",
      status: "started",
    },
  ];
  await page.route("**/api/snapshot", (r) => r.fulfill({ json: snapshot }));
  await page.route("**/api/definitions", (r) => r.fulfill({ json: {} }));
  await page.goto("/");
  await page.getByRole("button", { name: "数据工程师", exact: true }).click();
  const step = page.locator('.jq-workflow [data-step="match"]');
  await expect(step).toContainText("状态未确认");
  await expect(step).toContainText("失败");
});
