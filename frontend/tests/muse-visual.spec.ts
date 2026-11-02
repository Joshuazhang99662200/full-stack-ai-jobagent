import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";
import type { Page } from "@playwright/test";

const reference = await readFile(
  new URL("./fixtures/muse-current-reference.css", import.meta.url),
  "utf8",
);
async function measurements(page: Page, selector: string, offset = 0) {
  return page.locator(selector).evaluateAll(
    (nodes, yOffset) =>
      nodes
        .filter((n) => n.checkVisibility())
        .map((n) => {
          const b = n.getBoundingClientRect(),
            s = getComputedStyle(n);
          return {
            x: Math.round(b.x * 100) / 100,
            y:
              Math.round((b.y - (b.width || b.height ? yOffset : 0)) * 100) /
              100,
            w: Math.round(b.width * 100) / 100,
            h: Math.round(b.height * 100) / 100,
            font: s.fontFamily,
            size: s.fontSize,
            weight: s.fontWeight,
            color: s.color,
            bg: s.backgroundColor,
            padding: s.padding,
            border: s.borderRadius,
            line: s.lineHeight,
            grid: s.gridTemplateColumns,
            list: s.listStyleType,
          };
        }),
    offset,
  );
}

for (const width of [375, 860, 1440])
  test(`current Muse geometry and computed styles match original CSS at ${width}px`, async ({
    page,
    context,
  }) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("/?demo=1");
    await page.locator(".muse-current [data-open]").first().waitFor();
    const root = page.locator(".muse-current"),
      offset = (await root.boundingBox())!.y;
    const golden = await context.newPage();
    await golden.setViewportSize({ width, height: 1000 });
    await golden.setContent(
      `<!doctype html><html lang="zh-CN"><style>${reference}.material-history{margin-top:14px}</style><body>${await root.innerHTML()}</body></html>`,
    );
    const selectors = [
      ".topbar-in",
      ".navtab",
      ".wrap",
      ".head-row",
      ".ctl",
      ".filters",
      ".ftab",
      ".trow.head",
      ".trow[data-open]",
      ".chan",
      ".match",
      ".prog",
      ".todo-btn",
    ];
    for (const selector of selectors)
      expect(
        await measurements(page, `.muse-current ${selector}`, offset),
        selector,
      ).toEqual(await measurements(golden, selector));
    await page
      .getByRole("button", { name: "查看详情：数据工程师", exact: true })
      .click();
    await page
      .getByRole("dialog")
      .getByRole("heading", { name: "岗位要点", exact: true })
      .waitFor();
    await golden.setContent(
      `<!doctype html><html lang="zh-CN"><style>${reference}.material-history{margin-top:14px}</style><body>${await root.innerHTML()}</body></html>`,
    );
    for (const selector of [
      ".scrim",
      ".modal",
      ".modal h2",
      ".meta",
      ".modal h3",
      "ul.pts",
      "textarea.greet",
      ".btnrow",
      ".btn",
      ".modal-actions",
    ])
      expect(
        await measurements(page, `.muse-current ${selector}`),
        selector,
      ).toEqual(await measurements(golden, selector));
    await golden.close();
  });
