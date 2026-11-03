import { test, expect, seed, storageKey } from "./secondaryFixtures";
import demo from "../src/demo.json" with { type: "json" };
test("personal badge counts jobs once and the action text routes to the personal tab", async ({
  page,
}) => {
  await seed(page);
  await page.evaluate((key) => {
    const value = JSON.parse(localStorage.getItem(key)!);
    const todo = value.state.todos[0];
    todo.status = "pending";
    value.state.todos.push({
      ...structuredClone(todo),
      todo_id: "SECOND_SYNTHETIC_TODO",
      question: "第二个合成问题",
    });
    localStorage.setItem(key, JSON.stringify(value));
  }, storageKey);
  await page.reload();
  const filter = page.locator('.jq-summary button[data-lane="needs"]');
  await expect(filter).toContainText("等你处理");
  await expect(filter.locator(".jq-personal-badge")).toHaveText("1");
  await expect(page.locator(".jq-attention")).toHaveCount(1);
  await page
    .getByRole("button", { name: "这份材料是否可以继续推进？", exact: true })
    .click();
  await expect(page.getByRole("tab", { name: "需要你决定" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
});
test("sort survives a browser reload and missing reasons do not expose a bare score", async ({
  page,
}) => {
  await page.getByLabel("岗位排序").selectOption("intake");
  await page.reload();
  await expect(page.getByLabel("岗位排序")).toHaveValue("intake");
  const snapshot = structuredClone(demo);
  snapshot.jobs[0].match_result!.overall = 1;
  snapshot.jobs[0].match_result!.strengths = [];
  await page.route("**/api/snapshot", (r) => r.fulfill({ json: snapshot }));
  await page.route("**/api/definitions", (r) => r.fulfill({ json: {} }));
  await page.goto("/?legacy=1");
  const row = page.locator('.jq-row[data-job="DEMO_A"]');
  await expect(row).toContainText("已保存匹配评估，具体理由尚未接入");
  await expect(row).not.toContainText("100%");
});
test("personal decisions on a closed role remain counted without reopening its business state", async ({
  page,
}) => {
  await seed(page);
  await page.evaluate((key) => {
    const value = JSON.parse(localStorage.getItem(key)!);
    const closed = value.state.jobs.find((j: any) => j.job_id === "DEMO_D");
    const todo = {
      ...structuredClone(value.state.todos[0]),
      todo_id: "CLOSED_FOLLOWUP",
      job_id: closed.job_id,
      contact_id: closed.contact_id,
      material_revision: closed.materials[0].revision,
      status: "pending",
      question: "确认已结束岗位的合成归档信息",
    };
    value.state.todos.push(todo);
    localStorage.setItem(key, JSON.stringify(value));
  }, storageKey);
  await page.reload();
  const needs = page.locator('.jq-summary button[data-lane="needs"]');
  await expect(needs.locator(".jq-personal-badge")).toHaveText("1");
  await expect(page.locator(".jq-attention")).toHaveCount(1);
  await needs.click();
  await expect(page.locator(".jq-row")).toHaveCount(1);
  await expect(page.locator(".jq-row")).toHaveAttribute("data-closed", "true");
});
