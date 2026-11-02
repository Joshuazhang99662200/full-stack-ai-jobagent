import { test, expect, seed, storageKey } from "./secondaryFixtures";
import demo from "../src/demo.json" with { type: "json" };
test("linked attachments show their material version and duplicate operations keep raw history", async ({
  page,
}) => {
  await seed(page);
  await page.evaluate((key) => {
    const value = JSON.parse(localStorage.getItem(key)!);
    const job = value.state.jobs[0],
      material = job.materials[0];
    material.label = "获批材料一版";
    material.attachments = [
      {
        name: "合成简历.pdf",
        url: "/synthetic-files/resume-a.pdf",
        digest: "sha256:SYNTHETIC_PRIVATE_HASH",
      },
    ];
    job.events[0].detail = "合成决定只展示一次";
    job.events[0].material = structuredClone(material);
    job.events.push({
      ...structuredClone(job.events[0]),
      event_id: "DUPLICATE_SYNTHETIC_EVENT",
    });
    localStorage.setItem(key, JSON.stringify(value));
  }, storageKey);
  await page.reload();
  await page.getByRole("button", { name: "数据工程师", exact: true }).click();
  await page.getByRole("tab", { name: "历史记录", exact: true }).click();
  await expect(
    page.getByText("合成决定只展示一次", { exact: true }),
  ).toHaveCount(1);
  const link = page.getByRole("link", { name: /打开 合成简历/ }).first();
  await expect(link).toHaveAttribute("href", "/synthetic-files/resume-a.pdf");
  await expect(link.locator("..")).toContainText("获批材料一版");
  await expect(page.getByRole("dialog")).not.toContainText(
    "SYNTHETIC_PRIVATE_HASH",
  );
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "更多", exact: true })
    .click();
  await page.getByRole("tab", { name: "排查问题", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText(
    "DUPLICATE_SYNTHETIC_EVENT",
  );
  await expect(page.getByRole("dialog")).toContainText("operation_key");
});
test("recorded progress is visible verbatim without fabricating a current task", async ({
  page,
}) => {
  await seed(page);
  const summary =
    "已核对合成岗位要求与现有材料，目前等待你审阅正文并决定是否继续推进；尚未发送消息，也未安排后续动作。";
  await page.evaluate(
    ({ key, summary }) => {
      const value = JSON.parse(localStorage.getItem(key)!);
      value.state.jobs[0].progress = summary;
      localStorage.setItem(key, JSON.stringify(value));
    },
    { key: storageKey, summary },
  );
  await page.reload();
  await page.getByRole("button", { name: "数据工程师", exact: true }).click();
  await expect(page.getByText(summary, { exact: true })).toBeVisible();
});
