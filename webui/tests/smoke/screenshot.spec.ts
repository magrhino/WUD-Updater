import { expect, test } from "@playwright/test";

const demoBasePath = process.env.PLAYWRIGHT_WEBUI_DEMO_BASE_PATH ?? "";

function demoRoute(path: string) {
  return `${demoBasePath}${path}`;
}

test("capture self-update modal screenshot", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(`http://127.0.0.1:4173${demoRoute("/#/pending")}`);

  // Wait for the app to load
  await expect(page.getByRole("heading", { name: "Pending updates", exact: true })).toBeVisible();

  // Try to click the "Update available:" button
  const bannerButton = page.locator('.self-update-banner-actions .n-button');
  
  await expect(bannerButton).toBeVisible();
  await bannerButton.click();
  
  await page.waitForSelector('.self-update-modal');
  // wait a bit for tabs animation
  await page.waitForTimeout(500);

  const artifactDir = '/Users/ryanjones/.gemini/antigravity/brain/2c09bb5f-ca18-4da1-bc6b-aff7c03db718';
  await page.locator('.n-modal').screenshot({ path: `${artifactDir}/modal-tab-1.png` });

  // switch to Release Notes tab
  await page.getByText('Release Notes').click();
  await page.waitForTimeout(500);
  
  await page.locator('.n-modal').screenshot({ path: `${artifactDir}/modal-tab-2.png` });
});
