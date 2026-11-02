import { expect, test } from "@playwright/test";
import demo from "../src/demo.json" with { type: "json" };

test.beforeEach(async ({ page }) => {
  await page.goto("/?demo=1");
  await page.evaluate(() => localStorage.clear());
  await page.reload();
});

test("material decisions persist without execution and history retains every full draft", async ({
  page,
}) => {
  await page.getByRole("button", { name: "数据工程师", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "放弃这个岗位", exact: true }),
  ).toBeVisible();
  await page.getByLabel("材料正文").fill("您好，这是修改后完整的合成正文。");
  await page.getByRole("button", { name: "保存草稿", exact: true }).click();
  await expect(page.getByRole("status").last()).toContainText("已保存");
  await page.getByRole("button", { name: "批准这份材料", exact: true }).click();
  await expect(page.getByRole("status").last()).toContainText("未触发发送");
  await page.getByRole("button", { name: "关闭详情", exact: true }).click();
  await page.reload();
  await page.getByRole("button", { name: "数据工程师", exact: true }).click();
  await expect(page.getByLabel("材料正文")).toHaveValue(
    "您好，这是修改后完整的合成正文。",
  );
  await expect(
    page.getByText("已记录材料批准，尚未执行", { exact: true }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "历史记录", exact: true }).click();
  await expect(
    page.getByText("您好，这是修改后完整的合成正文。", { exact: true }).first(),
  ).toBeVisible();
  await expect(page.getByText("初稿（合成）", { exact: true })).toBeVisible();
});

test("personal todo dots survive viewing; only a saved answer clears them", async ({
  page,
}) => {
  await expect(page.locator(".jq-attention")).toHaveCount(1);
  await expect(page.locator(".jq-attention .host-dot")).toHaveCSS(
    "background-color",
    "rgb(182, 60, 54)",
  );
  await page.locator(".jq-attention").click();
  await expect(
    page.getByRole("heading", { name: "需要你决定", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", {
      name: "这份材料是否可以继续推进？",
      exact: true,
    }),
  ).toBeVisible();
  await page.getByRole("button", { name: "关闭详情", exact: true }).click();
  await expect(page.locator(".jq-attention")).toHaveCount(1);
  await page.locator(".jq-attention").click();
  await page.getByRole("button", { name: "暂缓推进", exact: true }).click();
  await expect(page.getByRole("status").last()).toContainText("已保存");
  await page.getByRole("button", { name: "关闭详情", exact: true }).click();
  await expect(page.locator(".jq-attention")).toHaveCount(0);
});

test("execution is a modal and requires explicit per-item selection and readback", async ({
  page,
}) => {
  await page.getByRole("button", { name: "数据工程师", exact: true }).click();
  await page.getByRole("button", { name: "批准这份材料", exact: true }).click();
  await expect(page.getByRole("status").last()).toContainText("已保存");
  await page.getByRole("button", { name: "关闭详情", exact: true }).click();
  await page.getByRole("button", { name: "执行清单", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  const confirm = page.getByRole("button", {
    name: "确认执行所选项目",
    exact: true,
  });
  await expect(confirm).toBeDisabled();
  await page.getByRole("checkbox", { name: /数据工程师/ }).check();
  await expect(
    page
      .getByText("您好，这是供审核的合成招呼语，尚未发送。", { exact: true })
      .first(),
  ).toBeVisible();
  await confirm.click();
  await expect(page.getByText("合成回读已核验", { exact: true })).toBeVisible();
  await expect(confirm).toBeDisabled();
});

test("login restore only records request and synthetic sync is labelled", async ({
  page,
}) => {
  await page.getByRole("button", { name: "渠道状态", exact: true }).click();
  await page.getByRole("button", { name: "请求恢复登录", exact: true }).click();
  await expect(page.getByRole("status").last()).toContainText(
    "尚未打开登录窗口",
  );
  await expect(
    page.getByRole("button", { name: "已请求恢复", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "关闭详情", exact: true }).click();
  await page.getByRole("button", { name: "核对同步", exact: true }).click();
  await expect(
    page.getByText("合成同步核对完成；未读取真实队列或真实渠道。", {
      exact: true,
    }),
  ).toBeVisible();
});

test("default view hides internal data and read-only operations explain their limitation", async ({
  page,
}) => {
  await page.goto("/");
  await page.route("**/api/**", (route) =>
    route.fulfill({ status: 503, body: "{}" }),
  );
  await page.goto("/?demo=1");
  await expect(page.locator(".context")).not.toContainText("CAND_");
  await expect(
    page.getByRole("tab", { name: "数据说明", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "更多", exact: true }).click();
  await page.getByRole("button", { name: "排查问题", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "接入时可用的数据", exact: true }),
  ).toBeVisible();
});

test("row keyboard, independent controls, sort and five columns work at mobile width", async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 900 });
  await page.getByLabel("岗位排序").selectOption("intake");
  const row = page.locator('.jq-row[data-job="DEMO_A"]');
  await row.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(row).toBeFocused();
  await page.getByRole("button", { name: "刷新", exact: true }).click();
  await expect(page.getByLabel("岗位排序")).toHaveValue("intake");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "../.jobagent/react-console-mobile.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({
    path: "../.jobagent/react-console-desktop.png",
    fullPage: true,
  });
});

test("an unknown save survives reload and only permits verification", async ({
  page,
}) => {
  await page.evaluate(() => {
    const original = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
      if (key.startsWith("ja-console.synthetic."))
        throw new Error("synthetic offline storage");
      return original.call(this, key, value);
    };
  });
  await page.getByRole("button", { name: "数据工程师", exact: true }).click();
  await page.getByRole("button", { name: "批准这份材料", exact: true }).click();
  await expect(page.getByRole("status").last()).toContainText("保存结果未确认");
  await expect(
    page.getByRole("button", { name: "批准这份材料", exact: true }),
  ).toBeDisabled();
  await page.reload();
  await page.getByRole("button", { name: "数据工程师", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "批准这份材料", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "核验保存结果", exact: true }).click();
  await expect(page.getByRole("status").last()).toContainText("尚无可核实");
});

test("readonly source explicitly disables decisions and does not infer personal dots", async ({
  page,
}) => {
  await page.route("**/api/snapshot", (route) => route.fulfill({ json: demo }));
  await page.route("**/api/definitions", (route) =>
    route.fulfill({ json: {} }),
  );
  await page.goto("/");
  await expect(page.locator(".jq-attention")).toHaveCount(0);
  await page.getByRole("button", { name: "数据工程师", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "批准这份材料", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByText("材料写入尚未接入，无法在面板内保存，请在对话中告知。", {
      exact: true,
    }),
  ).toBeVisible();
});

test("previous contact text remains readable in history without opening diagnostics", async ({
  page,
}) => {
  const snapshot = structuredClone(demo);
  const old = structuredClone(snapshot.jobs[0]);
  old.job.pipeline_id = "PIPE_OLD_SYNTHETIC";
  old.job.pipeline_state = "abandoned";
  old.job.sent_greeting = "这是旧联系轮次实际发送的合成全文。";
  snapshot.jobs.push(old);
  await page.route("**/api/snapshot", (route) =>
    route.fulfill({ json: snapshot }),
  );
  await page.route("**/api/definitions", (route) =>
    route.fulfill({ json: {} }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: "数据工程师", exact: true }).click();
  await page.getByRole("tab", { name: "历史记录", exact: true }).click();
  await expect(
    page.getByText("这是旧联系轮次实际发送的合成全文。", { exact: true }),
  ).toBeVisible();
});

test("the whole row opens detail while text selection and independent links do not", async ({
  page,
}) => {
  const row = page.locator('.jq-row[data-job="DEMO_A"]');
  await row.locator(".jq-company").click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await row.locator(".jq-company").evaluate((el) => {
    const range = document.createRange();
    range.selectNodeContents(el);
    window.getSelection()!.removeAllRanges();
    window.getSelection()!.addRange(range);
    el.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  await expect(page.getByRole("dialog")).toHaveCount(0);
});
