import { test, expect } from "@playwright/test";
import demo from "../src/demo.json" with { type: "json" };

test("channel opens a modal with keyboard dismissal and restores focus", async ({
  page,
}) => {
  await page.goto("/?legacy=1&demo=1");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.locator(".jq-details")).toHaveCount(0);
  const channel = page
    .locator('.jq-row[data-job="DEMO_A"]')
    .getByRole("button", { name: /BOSS.*详情/ });
  await channel.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(
    dialog.getByRole("heading", { name: "数据工程师", exact: true }),
  ).toBeVisible();
  await expect(dialog.getByRole("tab", { name: "招呼与材料" })).toBeVisible();
  const close = dialog.getByRole("button", { name: "关闭详情" });
  await close.focus();
  await page.keyboard.press("Shift+Tab");
  await expect(dialog.locator(":focus")).toHaveCount(1);
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(channel).toBeFocused();
});

test("Liepin routes materials without greeting steps and preserves raw records", async ({
  page,
}) => {
  const snapshot: any = structuredClone(demo);
  snapshot.jobs[0].job.platform = "liepin";
  snapshot.jobs[0].job.draft_greeting = "PRIVATE_GREETING_FOR_AUDIT";
  snapshot.runs[0].activities[0].activity = "draft_greeting";
  await page.route("**/api/snapshot", (route) =>
    route.fulfill({ json: snapshot }),
  );
  await page.route("**/api/definitions", (route) =>
    route.fulfill({ json: {} }),
  );
  await page.goto("/?legacy=1");
  const row = page.locator('.jq-row[data-job="DEMO_A"]');
  await expect(row).not.toContainText("招呼");
  await row.getByRole("button", { name: /猎聘.*详情/ }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("tab", { name: "招呼与材料" })).toHaveCount(0);
  await dialog.getByRole("tab", { name: "投递与材料" }).click();
  await expect(dialog).not.toContainText("PRIVATE_GREETING_FOR_AUDIT");
  await expect(dialog).not.toContainText("招呼");
  await expect(dialog.getByRole("region", { name: "工作流程" })).toBeVisible();
  await dialog.getByRole("button", { name: "更多", exact: true }).click();
  await dialog.getByRole("tab", { name: "排查问题" }).click();
  await expect(dialog).toContainText("PRIVATE_GREETING_FOR_AUDIT");
  await dialog.getByRole("button", { name: "关闭详情" }).click();
  await page.getByRole("tab", { name: "沟通进展", exact: true }).click();
  await page.getByRole("button", { name: /数据工程师/ }).click();
  await expect(
    page.locator('.states [data-work-state="greeting_sent"]'),
  ).toHaveCount(0);
  await expect(
    page.locator('.states [data-work-state="greeting_read"]'),
  ).toHaveCount(0);
});

test("workflow shows recorded completion, concurrent current work and unknown steps on every tab", async ({
  page,
}) => {
  const snapshot: any = structuredClone(demo);
  const event = snapshot.runs[0].activities[0];
  snapshot.runs = [snapshot.runs[0]];
  snapshot.runs[0].freshness = "current";
  snapshot.runs[0].activities = [
    {
      ...event,
      event_id: "WF_FETCH",
      activity_id: "WF_FETCH",
      job_id: "DEMO_A",
      activity: "fetch",
      status: "completed",
      next_step: null,
    },
    {
      ...event,
      event_id: "WF_MATCH",
      activity_id: "WF_MATCH",
      job_id: "DEMO_A",
      activity: "match",
      status: "started",
      next_step: "检查材料",
    },
    {
      ...event,
      event_id: "WF_REVIEW",
      activity_id: "WF_REVIEW",
      job_id: "DEMO_A",
      activity: "review",
      status: "waiting",
      next_step: null,
    },
  ];
  await page.route("**/api/snapshot", (route) =>
    route.fulfill({ json: snapshot }),
  );
  await page.route("**/api/definitions", (route) =>
    route.fulfill({ json: {} }),
  );
  await page.goto("/?legacy=1");
  await page.locator('.jq-row[data-job="DEMO_A"] .jq-job').click();
  const flow = page.getByRole("region", { name: "工作流程" });
  await expect(flow).toBeVisible();
  await expect(flow.locator('[data-step="fetch"]')).toHaveAttribute(
    "data-work-state",
    "completed",
  );
  await expect(flow.locator('[data-step="fetch"]')).toHaveCSS(
    "color",
    "rgb(40, 106, 164)",
  );
  await expect(flow.locator('[data-step="match"]')).toContainText(
    "现在 · 执行中",
  );
  await expect(flow.locator('[data-step="review"]')).toContainText(
    "现在 · 等待处理",
  );
  await expect(flow.locator('[data-step="detail"]')).toContainText("未记录");
  await expect(flow.locator('[data-step="detail"]')).toHaveAttribute(
    "data-work-state",
    "missing",
  );
  await expect(flow.locator('[data-step="detail"]')).toHaveCSS(
    "color",
    "rgb(100, 113, 132)",
  );
  await expect(flow.locator('[data-step="next"]')).toContainText(
    "计划 · 检查材料",
  );
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "更多", exact: true })
    .click();
  await page.getByRole("tab", { name: "排查问题" }).click();
  await expect(flow).toBeVisible();
});

test("workflow does not turn stale, failed or closed work into current or completed nodes", async ({
  page,
}) => {
  const snapshot: any = structuredClone(demo);
  const event = snapshot.runs[0].activities[0];
  snapshot.runs = [snapshot.runs[0]];
  snapshot.runs[0].freshness = "stale";
  snapshot.runs[0].activities = [
    {
      ...event,
      event_id: "WF_STALE",
      activity_id: "WF_STALE",
      job_id: "DEMO_A",
      activity: "match",
      status: "started",
      next_step: null,
    },
    {
      ...event,
      event_id: "WF_FAILED",
      activity_id: "WF_FAILED",
      job_id: "DEMO_A",
      activity: "fetch",
      status: "failed",
      next_step: null,
    },
  ];
  await page.route("**/api/snapshot", (route) =>
    route.fulfill({ json: snapshot }),
  );
  await page.route("**/api/definitions", (route) =>
    route.fulfill({ json: {} }),
  );
  await page.goto("/?legacy=1");
  await page.locator('.jq-row[data-job="DEMO_A"] .jq-job').click();
  const flow = page.getByRole("region", { name: "工作流程" });
  await expect(flow.locator('[data-step="match"]')).toContainText("状态未确认");
  await expect(flow.locator('[data-step="fetch"]')).toContainText("失败");
  await expect(flow.locator('[aria-current="step"]')).toHaveCount(0);
  await page.getByRole("button", { name: "关闭详情" }).click();
  await page.locator('.jq-row[data-job="DEMO_D"] .jq-job').click();
  await expect(flow).toContainText("已放弃 / 关闭");
  await expect(flow.locator('[aria-current="step"]')).toHaveCount(0);
});

test("mobile dialog fits the viewport and missing sources stay explicit", async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 750 });
  await page.goto("/?legacy=1&demo=1");
  await page.locator(".jq-job").first().click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "更多", exact: true }).click();
  await dialog.getByRole("tab", { name: "Signal / Harness" }).click();
  await expect(dialog).toContainText("Signal 尚未接入");
  const box = await dialog.boundingBox();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(320);
  expect(box!.height).toBeLessThanOrEqual(750);
});
