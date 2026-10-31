import { test, expect } from "@playwright/test";
import demo from "../src/demo.json" with { type: "json" };

test("mobile queue phase key remains readable and embedded history avoids duplicate pickers", async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 1000 });
  await page.goto("/?demo=1");
  await expect(page.locator(".jq-stage-key").first()).toContainText("采集");
  await expect(page.locator(".jq-details .job-list")).toHaveCount(0);
  await expect(
    page.locator(".jq-details h2").filter({ hasText: "数据工程师" }),
  ).toHaveCount(1);
  await page.getByRole("tab", { name: "岗位九态" }).click();
  await expect(page.locator(".job-list button").last()).toContainText(
    "放弃 / 关闭",
  );
});

test("paused jobs are explicit and parallel detail controls identify their start time", async ({
  page,
}) => {
  await page.goto("/?demo=1");
  await expect(page.locator('.jq-row[data-job="DEMO_E"]')).toContainText(
    "已暂停",
  );
  const controls = page
    .locator(".jq-phase-controls button")
    .filter({ hasText: "读取详情" });
  await expect(controls).toHaveCount(2);
  const names = await controls.allTextContents();
  expect(new Set(names).size).toBe(2);
  for (const button of await controls.all())
    await expect(button).toHaveAttribute("aria-label", /RUN_/);
});

async function fixture(page: import("@playwright/test").Page) {
  const snapshot: any = structuredClone(demo);
  snapshot.jobs.forEach((job: any, index: number) => {
    job.job.pipeline_state = "draft_pending";
    job.hard_filter_result = { decision: "pass", reasons: [] };
    job.match_result = { overall: [0.8, 0.95, 0.6, 0.5][index] || 0.5 };
  });
  snapshot.jobs[2].job.pipeline_state = "abandoned";
  snapshot.jobs[2].match_result.overall = 0.99;
  const run = snapshot.runs[0];
  run.activities.forEach((e: any) => (e.job_id = snapshot.jobs[0].job.job_id));
  const first = run.activities.slice(0, 2).map((e: any) => ({
    ...e,
    event_id: e.event_id + "_SECOND",
    activity_id: e.activity_id + "_SECOND",
    job_id: snapshot.jobs[1].job.job_id,
  }));
  const overlap = run.activities.slice(0, 2).map((e: any) => ({
    ...e,
    event_id: e.event_id + "_OVERLAP",
    activity_id: e.activity_id + "_OVERLAP",
    activity: "review",
  }));
  run.activities.push(...first, ...overlap, {
    ...run.activities.at(-1),
    event_id: "UNBOUND_TEST",
    activity_id: "UNBOUND_TEST",
    job_id: null,
  });
  await page.route("**/api/snapshot", (route) =>
    route.fulfill({ json: snapshot }),
  );
  await page.route("**/api/definitions", (route) =>
    route.fulfill({ json: {} }),
  );
  return snapshot;
}
test("primary queue ranks stored pass and match while abandoned stays last", async ({
  page,
}) => {
  const snapshot = await fixture(page);
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "岗位任务队列", exact: true }),
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
test("jobs share absolute time positions and concurrent activities get separate sublanes", async ({
  page,
}) => {
  const snapshot = await fixture(page);
  await page.goto("/");
  const a = page.locator(`.jq-row[data-job="${snapshot.jobs[0].job.job_id}"]`);
  const b = page.locator(`.jq-row[data-job="${snapshot.jobs[1].job.job_id}"]`);
  await expect(a).toBeVisible();
  await expect(b).toBeVisible();
  const startsA = await a.locator(".jq-mark").evaluateAll((items) =>
    items.map((el) => ({
      start: el.getAttribute("data-start"),
      left: (el as HTMLElement).style.left,
      top: (el as HTMLElement).style.top,
    })),
  );
  const startsB = await b.locator(".jq-mark").evaluateAll((items) =>
    items.map((el) => ({
      start: el.getAttribute("data-start"),
      left: (el as HTMLElement).style.left,
    })),
  );
  expect(startsA.length).toBeGreaterThan(1);
  expect(startsB.length).toBeGreaterThan(0);
  expect(startsA[0].left).toBe(
    startsB.find((e) => e.start === startsA[0].start)!.left,
  );
  expect(
    startsA.filter((e) => e.start === startsA[0].start).map((e) => e.top)
      .length,
  ).toBeGreaterThan(1);
  expect(
    new Set(
      startsA.filter((e) => e.start === startsA[0].start).map((e) => e.top),
    ).size,
  ).toBeGreaterThan(1);
  await expect(page.locator(".jq-unbound")).toContainText("未绑定岗位");
  await expect(
    page.locator('.jq-mark[data-activity="UNBOUND_TEST"]'),
  ).toHaveCount(0);
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
  await page.getByText("全部联系轮次（2）", { exact: true }).click();
  await expect(page.getByText(/OLD_CONTACT_HISTORY/)).toBeVisible();
});

test("ambiguous active rounds remain above closed jobs and do not claim a current state", async ({
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
  await page
    .locator(".jq-job")
    .filter({ hasText: snapshot.jobs[0].job.title })
    .click();
  await expect(page.locator(".jq-details").getByRole("status")).toContainText(
    "存在多个未关闭联系轮次",
  );
  await expect(page.locator(".jq-details [data-state]")).toHaveCount(0);
});
