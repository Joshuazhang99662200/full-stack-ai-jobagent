import { expect, test } from "@playwright/test";
import demo from "../src/demo.json" with { type: "json" };

test("run selection reveals recorded activity; URL remembers view and selection", async ({
  page,
}) => {
  await page.goto("/?demo=1&view=runs");
  await expect(
    page.getByRole("heading", { name: "岗位进展", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: /RUN_AAAAAAAA/ }).click();
  await page.getByRole("button", { name: "查看详情", exact: true }).click();
  await expect(page.locator(".detail > p").first()).toHaveText(
    "正在读取岗位详情，恢复点已保存。",
  );
  await page.getByRole("button", { name: /RUN_BBBBBBBB/ }).click();
  await page.getByRole("button", { name: "待审批", exact: true }).click();
  await expect(page.locator(".detail > p").first()).toHaveText(
    "等待本人逐项审批。",
  );
  await page.getByRole("tab", { name: "沟通进展" }).click();
  await expect(page).toHaveURL(/view=jobs/);
  await page.reload();
  await expect(page.getByRole("tab", { name: "沟通进展" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
});

test("nine states highlight only recorded history and preserve full private content", async ({
  page,
}) => {
  await page.goto("/?demo=1&view=jobs");
  await page.getByRole("button", { name: /交互设计师/ }).click();
  await expect(page.locator("[data-state]")).toHaveCount(9);
  await expect(page.locator('[data-state="resume_sent"]')).toHaveAttribute(
    "data-visited",
    "false",
  );
  await expect(
    page.locator('[data-state="interview_pending"]'),
  ).toHaveAttribute("aria-current", "step");
  await page.getByText("查看岗位原始数据", { exact: true }).click();
  await expect(
    page.getByText("这是完整的合成 JD 正文。最后一行也必须保留。", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByText("您好，这是供审核的合成招呼语，尚未发送。", { exact: true }),
  ).toBeVisible();
});

test("production error never silently falls back to synthetic data", async ({
  page,
}) => {
  await page.route("**/api/**", (route) =>
    route.fulfill({ status: 503, body: "{}" }),
  );
  await page.goto("/?view=runs");
  await expect(page.getByRole("alert")).toContainText("读取失败");
  await expect(page.getByText("合成示例", { exact: true })).toHaveCount(0);
});

test("loading and verified empty snapshot are distinct", async ({ page }) => {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/snapshot", async (route) => {
    await gate;
    await route.fulfill({
      json: {
        schema_version: "1.0",
        candidate_id: "CAND_DEMO",
        generated_at: "2026-10-31T00:00:00Z",
        sources: [{ name: "harness", status: "complete", message: null }],
        jobs: [],
        runs: [],
        approvals: [],
      },
    });
  });
  await page.route("**/api/definitions", (route) =>
    route.fulfill({ json: { snapshot: {}, activity: {} } }),
  );
  await page.goto("/?view=runs");
  await expect(page.getByRole("status")).toContainText("正在读取");
  release();
  await expect(
    page.getByText("还没有运行记录。", { exact: true }),
  ).toBeVisible();
});

test("missing sources never masquerade as a verified empty result", async ({
  page,
}) => {
  await page.route("**/api/snapshot", (route) =>
    route.fulfill({
      json: {
        ...demo,
        runs: [],
        jobs: [],
        sources: [
          { name: "harness", status: "missing", message: "Unavailable" },
          { name: "pipeline", status: "invalid", message: "Invalid" },
        ],
      },
    }),
  );
  await page.route("**/api/definitions", (route) =>
    route.fulfill({ json: {} }),
  );
  await page.goto("/?view=runs");
  await expect(
    page.getByText("暂时无法读取运行记录。", { exact: true }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "沟通进展" }).click();
  await expect(
    page.getByText("暂时无法读取岗位记录。", { exact: true }),
  ).toBeVisible();
});

for (const freshness of ["unknown", "terminal"]) {
  test(`${freshness} activity freshness is unconfirmed in both mark and details`, async ({
    page,
  }) => {
    const snapshot = structuredClone(demo);
    snapshot.runs[0].freshness = freshness;
    if (freshness === "terminal") snapshot.runs[0].run.phase = "completed";
    await page.route("**/api/snapshot", (route) =>
      route.fulfill({ json: snapshot }),
    );
    await page.route("**/api/definitions", (route) =>
      route.fulfill({ json: {} }),
    );
    await page.goto("/?view=runs");
    await expect(
      page.locator(".detail .facts").getByText("状态未确认", { exact: true }),
    ).toBeVisible();
    expect(
      await page.locator(".lane").first().locator(".span.stale").count(),
    ).toBeGreaterThan(0);
    await expect(
      page.locator(".lane").first().locator(".span.heartbeat"),
    ).toHaveCount(0);
  });
}

test("mobile phases use full-label touch controls instead of narrow interactive marks", async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 1000 });
  await page.goto("/?demo=1&view=runs");
  await expect(page.locator(".track button")).toHaveCount(0);
  const phase = page.getByRole("button", { name: "获取信息", exact: true });
  await expect(phase).toBeVisible();
  const bounds = await phase.boundingBox();
  expect(bounds!.height).toBeGreaterThanOrEqual(44);
  expect(bounds!.width).toBeGreaterThanOrEqual(44);
  await phase.click();
  await expect(page.locator(".detail h3")).toHaveText("获取信息");
});

for (const width of [320, 375, 768, 1440, 1920]) {
  test(`layout fits ${width}px and all views remain accessible`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("/?demo=1&view=runs");
    for (const view of ["任务进度", "运行记录", "沟通进展", "数据说明"]) {
      await page.getByRole("tab", { name: view }).click();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      const escaped = await page.locator("button").evaluateAll((items) =>
        items
          .filter((el) => {
            const box = el.getBoundingClientRect();
            return box.width > 0 && (box.left < 0 || box.right > innerWidth);
          })
          .map((el) => el.textContent),
      );
      expect(escaped).toEqual([]);
    }
  });
}
