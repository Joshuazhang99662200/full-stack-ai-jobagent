import { test, expect, seed, storageKey } from "./secondaryFixtures";
import demo from "../src/demo.json" with { type: "json" };
test("sent text is gray italic readonly and cannot become a draft", async ({
  page,
}) => {
  await page.getByRole("button", { name: "交互设计师", exact: true }).click();
  const sent = page.locator(".host-sent-body");
  await expect(sent).toContainText("已核验回读的合成历史招呼语");
  await expect(sent).toHaveCSS("font-style", "italic");
  await expect(page.getByLabel("材料正文", { exact: true })).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "保存草稿", exact: true }),
  ).toHaveCount(0);
  const abandon = page.getByRole("button", {
    name: "放弃这个岗位",
    exact: true,
  });
  await expect(abandon).toHaveCSS("color", "rgb(139, 51, 43)");
  expect(
    await abandon.evaluate((el) => el.closest(".host-buttons") === null),
  ).toBe(true);
});
test("detail execution entry scopes its modal to the current job and restores the parent", async ({
  page,
}) => {
  await seed(page);
  await page.getByRole("button", { name: "数据工程师", exact: true }).click();
  await page.getByRole("button", { name: "审批并发送", exact: true }).click();
  const dialog = page.getByRole("dialog", {
    name: "逐项核对执行清单",
    exact: true,
  });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("checkbox")).toHaveCount(1);
  await expect(dialog.getByRole("checkbox").first()).toHaveAccessibleName(
    /数据工程师/,
  );
  await dialog.getByRole("button", { name: "关闭详情", exact: true }).click();
  await expect(
    page.getByRole("dialog", { name: "数据工程师", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "审批并发送", exact: true }),
  ).toBeFocused();
});
test("delivery entry is explicit and unavailable services never pretend to execute", async ({
  page,
}) => {
  const snapshot = structuredClone(demo);
  snapshot.jobs[0].job.platform = "liepin";
  await page.route("**/api/snapshot", (r) => r.fulfill({ json: snapshot }));
  await page.route("**/api/definitions", (r) => r.fulfill({ json: {} }));
  await page.goto("/");
  await page.getByRole("button", { name: "数据工程师", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "审批并投递", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "审批并发送", exact: true }),
  ).toHaveCount(0);
  await expect(page.getByRole("dialog")).toContainText("当前未接入执行服务");
  await page.getByRole("tab", { name: "投递与材料" }).click();
  await expect(page.getByRole("dialog")).toContainText("逐岗附件传输");
});
test("a changed draft opens a fresh single-job checklist after renewed approval", async ({
  page,
}) => {
  await seed(page);
  await page.getByRole("button", { name: "数据工程师", exact: true }).click();
  await page.getByRole("button", { name: "审批并发送", exact: true }).click();
  await page
    .getByRole("dialog", { name: "逐项核对执行清单" })
    .getByRole("button", { name: "关闭详情" })
    .click();
  await page
    .getByLabel("材料正文", { exact: true })
    .fill("新版合成材料，必须重新审批并核对后执行。");
  await page.getByRole("button", { name: "保存草稿", exact: true }).click();
  await expect(page.getByRole("status").last()).toContainText("已保存");
  await page.getByRole("button", { name: "批准这份材料", exact: true }).click();
  await expect(page.getByRole("status").last()).toContainText("已保存");
  await page.getByRole("button", { name: "审批并发送", exact: true }).click();
  const modal = page.getByRole("dialog", { name: "逐项核对执行清单" });
  await expect(modal).toContainText("新版合成材料，必须重新审批并核对后执行。");
  await expect(modal).not.toContainText(
    "您好，这是供审核的合成招呼语，尚未发送。",
  );
});
