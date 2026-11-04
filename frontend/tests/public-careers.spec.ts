import { expect, test } from "@playwright/test";
import demo from "../src/demo.json" with { type: "json" };

async function source(page: import("@playwright/test").Page, extra: object) {
  await page.route("**/api/snapshot", (route) =>
    route.fulfill({ json: { ...demo, ...extra } }),
  );
  await page.route("**/api/definitions", (route) =>
    route.fulfill({ json: {} }),
  );
  await page.goto("/?legacy=1");
}

test("a missing public source is distinct from a verified empty search", async ({
  page,
}) => {
  await source(page, {});
  await page.getByRole("tab", { name: "公开职位补充", exact: true }).click();
  await expect(
    page.getByText("公开职位补充尚未接入。", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("本次已完成读取，没有符合条件的补充岗位。", { exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: /发送|投递|批准/ }),
  ).toHaveCount(0);
});

const listing = {
  source: "public_careers:greenhouse:synthetic-board",
  source_job_id: "101",
  title: "合成公开岗位",
  company: "合成企业",
  location: "上海",
  url: "https://boards.greenhouse.io/synthetic-board/jobs/101",
};
const record = {
  candidate_id: "CAND_DEMO",
  channel: "public_careers",
  provider: "greenhouse",
  board: "synthetic-board",
  source_job_id: "101",
  job_id: "JOB_AAAAAAAAAAAAAAAA",
  run_id: "SYNTHETIC_RUN",
  listing,
  region_decision: "review",
  observation: {
    completeness: "full",
    jd_raw: "完整合成JD。<script>window.injected=true</script>最后一行。",
  },
};

test("the supplementary channel retains source and full text without sending controls", async ({
  page,
}) => {
  await source(page, {
    public_careers: {
      status: "complete",
      records: [record],
      runs: [
        {
          candidate_id: "CAND_DEMO",
          status: "partial",
          raw_returned: 4,
          taken: 1,
        },
      ],
    },
  });
  await page.getByRole("tab", { name: "公开职位补充", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "合成公开岗位", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("地区条件待核对", { exact: true })).toBeVisible();
  await page.getByText("查看完整职位说明", { exact: true }).click();
  await expect(
    page.getByText(record.observation.jd_raw, { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "查看原始岗位" }),
  ).toHaveAttribute("href", listing.url);
  expect(
    await page.evaluate(
      () => (window as unknown as { injected?: boolean }).injected,
    ),
  ).toBeUndefined();
  await expect(
    page.getByRole("button", { name: /发送|投递|批准/ }),
  ).toHaveCount(0);
  await expect(
    page.getByText("本轮读取尚未完成，已保存的岗位可继续查看。", {
      exact: true,
    }),
  ).toBeVisible();
});

test("a completed empty run and a failed run have different messages", async ({
  page,
}) => {
  await source(page, {
    public_careers: {
      status: "complete",
      records: [],
      runs: [{ candidate_id: "CAND_DEMO", status: "complete" }],
    },
  });
  await page.getByRole("tab", { name: "公开职位补充", exact: true }).click();
  await expect(
    page.getByText("本次已完成读取，没有符合条件的补充岗位。", { exact: true }),
  ).toBeVisible();
  await page.unroute("**/api/snapshot");
  await source(page, {
    public_careers: {
      status: "complete",
      records: [],
      runs: [{ candidate_id: "CAND_DEMO", status: "failed" }],
    },
  });
  await page.getByRole("tab", { name: "公开职位补充", exact: true }).click();
  await expect(
    page.getByText("本轮读取尚未完成，已保存的岗位可继续查看。", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByText("本次已完成读取，没有符合条件的补充岗位。", { exact: true }),
  ).toHaveCount(0);
});

test("a foreign candidate discovery fails closed", async ({ page }) => {
  await source(page, {
    public_careers: {
      status: "complete",
      records: [{ ...record, candidate_id: "CAND_OTHER" }],
      runs: [],
    },
  });
  await expect(page.getByRole("alert")).toContainText("候选人");
  await expect(page.getByText("合成公开岗位", { exact: true })).toHaveCount(0);
});

test("an unsafe original link is omitted", async ({ page }) => {
  await source(page, {
    public_careers: {
      status: "complete",
      records: [
        { ...record, listing: { ...listing, url: "javascript:alert(1)" } },
      ],
      runs: [],
    },
  });
  await page.getByRole("tab", { name: "公开职位补充", exact: true }).click();
  await expect(page.getByRole("link", { name: "查看原始岗位" })).toHaveCount(0);
});
