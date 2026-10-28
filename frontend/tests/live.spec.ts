import { expect, test } from "@playwright/test";

test("live API completes a puzzle and restores it after reload", async ({ page }, testInfo) => {
  test.skip(process.env.PIXLE_LIVE_API !== "true", "Start a configured API and set PIXLE_LIVE_API=true");
  await page.goto("/");
  await expect(page.getByRole("combobox")).toBeEnabled();
  await expect(page.getByRole("img")).toBeVisible();
  await expect(page.getByText("Loading mosaic...", { exact: true })).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("initial.png"), fullPage: true });
  await page.getByRole("combobox").fill("Tay");
  await page.getByRole("option", { name: "Taylor Swift" }).click();
  await page.getByRole("button", { name: "Make a guess" }).click();
  await expect(page.getByRole("img", { name: /detail level 2/ })).toBeVisible();
  await page.reload();
  await expect(page.getByText("Taylor Swift", { exact: true })).toBeVisible();
  await page.getByRole("combobox").fill("Einstein");
  await page.getByRole("option", { name: "Albert Einstein" }).click();
  await page.getByRole("button", { name: "Make a guess" }).click();
  await expect(page.getByRole("heading", { name: "You saw it." })).toBeVisible();
  await expect(page.getByText("400", { exact: true }).first()).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "You saw it." })).toBeVisible();
  await expect(page.getByRole("region", { name: "Your statistics" }).getByText("400")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("result.png"), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
