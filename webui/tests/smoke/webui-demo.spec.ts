import { expect, test } from "@playwright/test";

test.skip(
  process.env.PLAYWRIGHT_WEBUI_DEMO !== "true",
  "demo smoke tests require the static demo Vite server",
);

test("static demo renders current pending state and completes apply flow", async ({
  page,
}) => {
  await page.goto("/#/pending");

  await expect(
    page.getByRole("heading", { name: "Pending updates", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("4 pending updates")).toBeVisible();
  await expect(page.getByText("Mutations enabled")).toBeVisible();
  await expect(
    page.getByTitle("ghcr.io/home-assistant/home-assistant:2026.5.1").first(),
  ).toBeVisible();

  await page.getByRole("button", { name: /Preview home plan/ }).click();
  await expect(page.getByRole("heading", { name: "Review home plan" })).toBeVisible();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: /Apply 1 update/ })
    .click();

  const applyDialog = page.getByRole("dialog").filter({
    hasText: "Apply complete",
  });
  await expect(applyDialog.getByRole("heading", { name: "Apply complete" })).toBeVisible();
  await expect(applyDialog.getByText("docker-update-from-wud-v2")).toBeVisible();
  await expect(page.getByText("3 pending updates")).toBeVisible();

  await applyDialog.getByRole("link", { name: "Details" }).click();
  await expect(page.getByRole("heading", { name: "#4" })).toBeVisible();
  await expect(page.getByText("Pending records")).toBeVisible();

  await page.getByRole("link", { name: "View log" }).click();
  await expect(page.getByRole("heading", { name: "#4 log" })).toBeVisible();
  await expect(page.getByText("Done. See log")).toBeVisible();
});

test("static demo mobile layout stays within the viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/#/pending");

  await expect(
    page.getByRole("heading", { name: "Pending updates", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("checkbox", { name: /Select stack media/ })).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(() => ({
        innerWidth: window.innerWidth,
        scrollWidth: document.documentElement.scrollWidth,
      })),
    )
    .toEqual({ innerWidth: 390, scrollWidth: 390 });
});
