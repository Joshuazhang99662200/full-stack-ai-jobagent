import { test, expect } from "@playwright/test";
import demo from "../src/demo.json" with { type: "json" };

test("queue and history retain the approved white, gray and pale-blue palette", async ({
  page,
}) => {
  await page.goto("/?demo=1");
  await expect(page.locator(".ja-console")).toHaveCSS(
    "background-color",
    "rgb(255, 255, 255)",
  );
  await expect(page.locator(".jq-flow .current").first()).toHaveCSS(
    "background-color",
    "rgb(228, 240, 255)",
  );
  await expect(page.locator(".jq-flow .done").first()).toHaveCSS(
    "background-color",
    "rgb(244, 246, 249)",
  );
  await page.getByRole("tab", { name: "运行记录" }).click();
  await expect(page.locator(".span.heartbeat").first()).toHaveCSS(
    "background-color",
    "rgb(228, 240, 255)",
  );
  await page.getByRole("tab", { name: "沟通进展" }).click();
  await expect(page.locator('.states [aria-current="step"]')).toHaveCSS(
    "background-color",
    "rgb(228, 240, 255)",
  );
});

test("each job reads as an agent report without a clock axis", async ({
  page,
}) => {
  await page.goto("/?demo=1");
  await expect(page.locator(".jq-axis, .jq-clock, .jq-window")).toHaveCount(0);
  await expect(page.getByText("最近30分钟")).toHaveCount(0);
  const a = page.locator('.jq-row[data-job="DEMO_A"]');
  await expect(a).toHaveAttribute("data-lane", "active");
  await expect(a.locator(".jq-flow .current")).toContainText("正在查看详情");
  await expect(a.locator(".jq-flow .next")).toContainText(
    "接下来：读完详情后评估匹配度。",
  );
  const b = page.locator('.jq-row[data-job="DEMO_B"]');
  await expect(b).toHaveAttribute("data-lane", "needs");
  await expect(b.locator(".jq-milestone")).toContainText("待面试");
  await expect(b.locator(".jq-ask").first()).toContainText(
    "审阅准确正文与附件，逐项批准",
  );
  const c = page.locator('.jq-row[data-job="DEMO_C"]');
  await expect(c.locator(".jq-flow .next")).toContainText("下一步尚未安排");
  await expect(c.locator(".jq-none")).toBeVisible();
});

test("summary counts filter jobs that need you", async ({ page }) => {
  await page.goto("/?demo=1");
  const needs = page.locator('.jq-summary button[data-lane="needs"]');
  await expect(needs).toContainText("需要你");
  const count = Number(await needs.locator("strong").textContent());
  expect(count).toBeGreaterThan(0);
  await needs.click();
  await expect(page.locator(".jq-row")).toHaveCount(count);
  for (const row of await page.locator(".jq-row").all())
    await expect(row).toHaveAttribute("data-lane", "needs");
  await page.getByRole("button", { name: "显示全部" }).click();
  await expect(page.locator(".jq-row")).toHaveCount(demo.jobs.length);
});

test("mobile queue stays readable and embedded history avoids duplicate pickers", async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 1000 });
  await page.goto("/?demo=1");
  await expect(page.locator(".jq-flow").first()).toBeVisible();
  await expect(page.locator(".jq-details .job-list")).toHaveCount(0);
  await page.getByRole("tab", { name: "沟通进展" }).click();
  await expect(page.locator(".job-list button").last()).toContainText(
    "放弃 / 关闭",
  );
});

test("paused jobs ask for a decision and parallel work controls identify their run", async ({
  page,
}) => {
  await page.goto("/?demo=1");
  await expect(page.locator('.jq-row[data-job="DEMO_E"]')).toContainText(
    "已暂停",
  );
  await expect(
    page
      .locator('.jq-row[data-job="DEMO_E"] .jq-ask')
      .filter({ hasText: "岗位已暂停，决定是否继续" }),
  ).toContainText("岗位已暂停，决定是否继续");
  await page.locator(".jq-job").filter({ hasText: "数据工程师" }).click();
  const controls = page
    .locator(".jq-phase-controls button")
    .filter({ hasText: "查看详情" });
  await expect(controls).toHaveCount(2);
  for (const button of await controls.all())
    await expect(button).toHaveAttribute("aria-label", /RUN_/);
});

async function fixture(page: import("@playwright/test").Page) {
  const snapshot: any = structuredClone(demo);
  snapshot.runs = [];
  snapshot.jobs.forEach((job: any, index: number) => {
    job.job.pipeline_state = "draft_pending";
    job.meta.paused = false;
    job.hard_filter_result = { decision: "pass", reasons: [] };
    job.match_result = { overall: [0.8, 0.95, 0.6, 0.5][index] || 0.5 };
  });
  snapshot.jobs[2].job.pipeline_state = "abandoned";
  snapshot.jobs[2].match_result.overall = 0.99;
  await page.route("**/api/snapshot", (route) =>
    route.fulfill({ json: snapshot }),
  );
  await page.route("**/api/definitions", (route) =>
    route.fulfill({ json: {} }),
  );
  return snapshot;
}
test("within a lane stored pass and match rank jobs while abandoned stays last", async ({
  page,
}) => {
  const snapshot = await fixture(page);
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "岗位进展", exact: true }),
  ).toBeVisible();
  const rows = page.locator(".jq-row");
  await expect(rows.first()).toHaveAttribute(
    "data-job",
    snapshot.jobs[1].job.job_id,
  );
  await expect(rows.last()).toHaveAttribute(
    "data-job",
    snapshot.jobs[2].job.job_id,
  );
});

test("unbound work is counted but never assigned to a job", async ({
  page,
}) => {
  await page.goto("/?demo=1");
  await expect(page.locator(".jq-unbound")).toContainText("没有注明所属岗位");
  await expect(page.locator(".jq-flow", { hasText: "整理结果" })).toHaveCount(
    0,
  );
});

test("canonical job keeps one row and preserves distinct contact rounds", async ({
  page,
}) => {
  const snapshot: any = structuredClone(demo);
  const active = snapshot.jobs[0];
  const old = structuredClone(active);
  old.job.pipeline_id = "PIPE_OLD_DEMO";
  old.job.pipeline_state = "abandoned";
  old.job.entered_at = "2026-10-01T00:00:00Z";
  old.meta.contact_round = 1;
  old.history = [{ history_id: "OLD_CONTACT_HISTORY", to_state: "abandoned" }];
  active.meta.contact_round = 2;
  active.meta.normalized_job_id = null;
  old.meta.normalized_job_id = "LEGACY_CANONICAL_EXACT";
  snapshot.jobs.push(old);
  await page.route("**/api/snapshot", (route) =>
    route.fulfill({ json: snapshot }),
  );
  await page.route("**/api/definitions", (route) =>
    route.fulfill({ json: {} }),
  );
  await page.goto("/");
  await expect(
    page.locator(`.jq-row[data-job="${active.job.job_id}"]`),
  ).toHaveCount(1);
  await page
    .getByRole("button", { name: active.job.title, exact: true })
    .first()
    .click();
  await expect(
    page.locator(`.jq-row[data-job="${active.job.job_id}"]`),
  ).toHaveAttribute("data-closed", "false");
  await page.getByText("历次联系记录（2）", { exact: true }).click();
  await expect(page.getByText(/OLD_CONTACT_HISTORY/)).toBeVisible();
});

test("ambiguous active rounds need you and do not claim a current state", async ({
  page,
}) => {
  const snapshot: any = structuredClone(demo);
  const duplicate = structuredClone(snapshot.jobs[0]);
  duplicate.job.pipeline_id = "PIPE_CONFLICT_DEMO";
  snapshot.jobs.push(duplicate);
  await page.route("**/api/snapshot", (route) =>
    route.fulfill({ json: snapshot }),
  );
  await page.route("**/api/definitions", (route) =>
    route.fulfill({ json: {} }),
  );
  await page.goto("/");
  await expect(page.locator(".jq-row").last()).toHaveAttribute(
    "data-closed",
    "true",
  );
  const row = page.locator(
    `.jq-row[data-job="${snapshot.jobs[0].job.job_id}"]`,
  );
  await expect(row).toHaveAttribute("data-lane", "needs");
  await row.locator(".jq-job").click();
  await expect(page.locator(".jq-details").getByRole("status")).toContainText(
    "这个岗位有多条尚未结束的联系记录",
  );
  await expect(page.locator(".jq-details [data-state]")).toHaveCount(0);
});
