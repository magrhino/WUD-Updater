import { expect, test, type Page } from "@playwright/test";

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
  await button.scrollIntoViewIfNeeded();
  const box = await button.boundingBox();
  expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
  expect(box?.width ?? 0).toBeGreaterThanOrEqual(44);
}

test("static demo renders current pending state and completes apply flow", async ({
  page,
}) => {
  await page.goto(demoRoute("/#/pending"));

  await expect(
    page.getByRole("heading", { name: "Pending updates", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("7 pending updates")).toBeVisible();
  await expect(page.getByText("Mutations enabled")).toBeVisible();
  await expect(page.getByText("3 items need review")).toBeVisible();
  await expect(
    page.getByTitle("ghcr.io/home-assistant/home-assistant:2026.5.1").first(),
  ).toBeVisible();

  await page.getByRole("button", { name: /Preview home plan/ }).click();
  await expect(page.getByRole("heading", { name: "Review home plan" })).toBeVisible();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: /Apply 1 update/ })
    .click();

  const applyPanel = page.locator(".apply-job-panel");
  await expect(applyPanel.getByRole("heading", { name: "Apply complete" })).toBeVisible();
  await expect(applyPanel.locator(".apply-job-latest-log code")).toContainText(
    "Done. See log",
  );
  await expect(applyPanel.locator(".apply-job-log-viewer")).toBeHidden();
  await applyPanel.getByRole("button", { name: "Show output" }).click();
  await expect(applyPanel.locator(".apply-job-log-viewer")).toBeVisible();
  await expect(applyPanel.locator(".apply-job-log-viewer")).toContainText(
    "docker-update-from-wud-v2",
  );
  await expect(page.getByText("6 pending updates")).toBeVisible();

  await applyPanel.getByRole("link", { name: "Details" }).click();
  await expect(page.getByRole("heading", { name: "#7" })).toBeVisible();
  await expect(page.getByText("Pending records")).toBeVisible();

  await page.getByRole("link", { name: "View log" }).click();
  await expect(page.getByRole("heading", { name: "#7 log" })).toBeVisible();
  await expect(page.getByText("Done. See log")).toBeVisible();
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
    page.getByText("Demo mode previews retag apply without changing local Compose files."),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Preview retag changes" }),
  ).toBeEnabled();
  const blockedServiceRow = page
    .getByRole("row")
    .filter({ hasText: "home/home-assistant" });
  await expect(blockedServiceRow.getByText("Concrete tracking")).toBeVisible();
  await expect(
    blockedServiceRow.getByRole("radio", { name: "Switch" }),
  ).toBeDisabled();
});

test("static demo mobile layout stays within the viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(demoRoute("/#/pending"));

  await expect(
    page.getByRole("heading", { name: "Pending updates", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("checkbox", { name: /Select stack media/ })).toBeVisible();
  await expectTouchTargetHeight(page, "Pull image");
  await expect
    .poll(() =>
      page.evaluate(() => ({
        innerWidth: window.innerWidth,
        scrollWidth: document.documentElement.scrollWidth,
      })),
    )
    .toEqual({ innerWidth: 390, scrollWidth: 390 });

  await page.goto(demoRoute("/#/doctor"));
  await expect(page.getByRole("heading", { name: "Doctor", level: 1 })).toBeVisible();
  await expectTouchTargetHeight(page, "Refresh");

  await page.goto(demoRoute("/#/settings"));
  await expect(page.getByRole("heading", { name: "Settings", level: 1 })).toBeVisible();
  await expectTouchTargetHeight(page, "Download support bundle");
  await expectTouchTargetHeight(page, "Copy");
});
