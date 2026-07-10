import { expect, test, type Page } from "@playwright/test";

import { responsiveBreakpoints } from "../../src/responsive";
import { touchTargetSizePx } from "../../src/touchTargets";

const demoBasePath = process.env.PLAYWRIGHT_WEBUI_DEMO_BASE_PATH ?? "";
const browserFailures = new WeakMap<Page, string[]>();

test.skip(
  process.env.PLAYWRIGHT_WEBUI_DEMO !== "true",
  "demo smoke tests require the static demo Vite server",
);

test.beforeEach(({ page }) => {
  const failures: string[] = [];
  browserFailures.set(page, failures);

  page.on("pageerror", (error) => {
    failures.push(`page error: ${error.message}`);
  });

  page.on("console", (message) => {
    if (message.type() === "error") {
      failures.push(`console error: ${message.text()}`);
    }
  });

  page.on("requestfailed", (request) => {
    const url = request.url();
    if (/^https?:\/\//i.test(url)) {
      failures.push(
        `request failed: ${request.method()} ${url}: ${
          request.failure()?.errorText ?? "unknown failure"
        }`,
      );
    }
  });
});

test.afterEach(({ page }) => {
  expect(browserFailures.get(page) ?? []).toEqual([]);
});

function demoRoute(path: string) {
  return `${demoBasePath}${path}`;
}

async function expectTouchTargetHeight(page: Page, buttonName: string) {
  const button = page
    .getByRole("button", { name: buttonName, exact: true })
    .first();
  await expect(button).toBeVisible();
  await button.scrollIntoViewIfNeeded();
  const box = await button.boundingBox();
  if (box === null) {
    throw new Error(`Expected "${buttonName}" button to have a bounding box`);
  }
  expect(box.height).toBeGreaterThanOrEqual(touchTargetSizePx);
  expect(box.width).toBeGreaterThanOrEqual(touchTargetSizePx);
}

async function expectNoHorizontalOverflow(page: Page, viewportWidth: number) {
  await expect
    .poll(() =>
      page.evaluate(() => ({
        innerWidth: window.innerWidth,
        hasHorizontalOverflow:
          document.documentElement.scrollWidth > window.innerWidth,
      })),
    )
    .toEqual({ innerWidth: viewportWidth, hasHorizontalOverflow: false });
}

test("static demo renders current pending state in read-only mode", async ({
  page,
}) => {
  await page.goto(demoRoute("/#/pending"));

  await expect(
    page.getByRole("heading", {
      name: "Pending updates",
      exact: true,
      level: 1,
    }),
  ).toBeVisible();
  await expect(page.getByText("7 pending updates")).toBeVisible();
  await expect(page.getByText("Read-only", { exact: true })).toBeVisible();
  await expect(page.getByText("3 items need review")).toBeVisible();
  const snoozedPanel = page
    .locator("article")
    .filter({ hasText: "Snoozed pending entries" });
  await expect(snoozedPanel).toBeVisible();
  await snoozedPanel.getByText("Details", { exact: true }).click();
  await expect(snoozedPanel.getByText("media / radarr").first()).toBeVisible();
  await expect(
    snoozedPanel.getByText(
      "lscr.io/linuxserver/radarr:5.21.1 -> lscr.io/linuxserver/radarr:5.23.0",
    ),
  ).toBeVisible();
  await expect(
    snoozedPanel.getByText("No matching pending update row."),
  ).toBeVisible();
  await expect(
    page.getByTitle("ghcr.io/home-assistant/home-assistant:2026.5.1").first(),
  ).toBeVisible();

  await page.getByRole("button", { name: /Preview home plan/ }).click();
  await expect(page.getByRole("heading", { name: "Review home plan" })).toBeVisible();
  const applyButton = page
    .getByRole("dialog")
    .getByRole("button", { name: /Apply 1 update/ });
  await expect(applyButton).toBeDisabled();
  await expect(
    page.getByText(
      "The public static demo is read-only. Run WUDup locally to apply changes.",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(page.getByText("7 pending updates")).toBeVisible();
});

test("static demo renders seeded audit log records", async ({ page }) => {
  await page.goto(demoRoute("/#/audit"));

  await expect(page.getByRole("heading", { name: "History", level: 1 })).toBeVisible();
  await expect(page.getByRole("link", { name: "All runs" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Audit log" })).toBeVisible();
  await expect(page.getByRole("link", { name: "#6" })).toBeVisible();
  await expect(page.getByText("Settings changed")).toBeVisible();
  await expect(page.getByText("webui_preferences")).toBeVisible();
  await expect(page.getByText("media/radarr")).toBeVisible();
  await expect(page.getByText("admin")).toBeVisible();
});

test("static demo renders retag review fixtures", async ({ page }) => {
  await page.goto(demoRoute("/#/retags"));

  await expect(page.getByRole("heading", { name: "Retags", level: 1 })).toBeVisible();
  await expect(page.getByText("Compose service tracking")).toBeVisible();
  await expect(page.getByText("media/wudup")).toBeVisible();
  await expect(page.getByText("Retag available").first()).toBeVisible();
  await expect(page.getByText("home/home-assistant")).toBeVisible();
  await expect(
    page.getByText(
      "Static demo mode is read-only. Preview stays available; apply is disabled.",
    ).first(),
  ).toBeVisible();
  const serviceRow = page
    .getByRole("row")
    .filter({ hasText: "media/wudup" });
  await expect(
    serviceRow.getByRole("radio", { name: "Retag" }),
  ).toBeEnabled();
  await serviceRow
    .getByRole("button", { name: "Retag only media/wudup" })
    .click();
  await expect(
    page.getByRole("button", { name: "Preview retag changes" }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Preview retag changes" }).click();
  await expect(
    page.getByRole("heading", { name: "Review retag preview" }),
  ).toBeVisible();
  await expect(page.getByText("1 service ready to retag.")).toBeVisible();
  await expect(
    page
      .getByLabel("Review retag preview")
      .getByRole("button", { name: "Apply selected retags" }),
  ).toBeDisabled();
});

test("static demo mobile layout stays within the viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(demoRoute("/#/"));
  await expect(page.getByRole("heading", { name: "Dashboard", level: 1 })).toBeVisible();
  await expect(page.getByLabel("System status")).toBeVisible();
  await expectNoHorizontalOverflow(page, 390);

  await page.goto(demoRoute("/#/pending"));

  await expect(
    page.getByRole("heading", {
      name: "Pending updates",
      exact: true,
      level: 1,
    }),
  ).toBeVisible();
  await expect(page.getByRole("checkbox", { name: /Select stack media/ })).toBeVisible();
  await expectTouchTargetHeight(page, "Pull image");
  await expectNoHorizontalOverflow(page, 390);

  await page.goto(demoRoute("/#/doctor"));
  await expect(page.getByRole("heading", { name: "Doctor", level: 1 })).toBeVisible();
  await expectTouchTargetHeight(page, "Refresh");

  await page.goto(demoRoute("/#/settings"));
  await expect(page.getByRole("heading", { name: "Settings", level: 1 })).toBeVisible();
  await expect(
    page.getByText(
      "The public static demo is read-only. Run WUDup locally to apply changes.",
    ).first(),
  ).toBeVisible();
  await expectTouchTargetHeight(page, "Download support bundle");
  await expectTouchTargetHeight(page, "Copy");

  await page.goto(demoRoute("/#/retags"));
  await expect(page.getByRole("heading", { name: "Retags", level: 1 })).toBeVisible();
  await expectTouchTargetHeight(page, "Preview retag changes");
  await expectTouchTargetHeight(page, "Retag only media/wudup");
  const retagChoiceGroup = page.locator(".retag-card .n-radio-group").first();
  const retagChoiceButtons = retagChoiceGroup.locator(".n-radio-button");
  await expect(retagChoiceGroup).toBeVisible();
  const keepBox = await retagChoiceButtons.nth(0).boundingBox();
  const retagBox = await retagChoiceButtons.nth(1).boundingBox();
  expect(keepBox?.height).toBeGreaterThanOrEqual(touchTargetSizePx);
  expect(retagBox?.height).toBeGreaterThanOrEqual(touchTargetSizePx);
  expect(keepBox?.y).toBe(retagBox?.y);
  await expectNoHorizontalOverflow(page, 390);

  for (const width of [
    responsiveBreakpoints.compact + 1,
    responsiveBreakpoints.dataCards,
  ]) {
    await page.setViewportSize({ width, height: 844 });
    await page.goto(demoRoute("/#/retags"));
    await expect(page.locator(".retag-card").first()).toBeVisible();
    await expectNoHorizontalOverflow(page, width);
  }
});
