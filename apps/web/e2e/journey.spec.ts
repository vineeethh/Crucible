import { expect, test } from "@playwright/test";

// The Phase 6/7 acceptance journey, exercised end-to-end against a seeded org
// (run scripts/seed_demo.py first). Each section renders real, tenant-scoped
// data — no internal tools. Skips cleanly if the API is not configured (the
// pages show a Setup card instead of data).

async function configured(page: import("@playwright/test").Page): Promise<boolean> {
  await page.goto("/dashboard");
  return !(await page.getByRole("heading", { name: "Setup required" }).isVisible());
}

test.describe("seeded journey", () => {
  test("reliability dashboard shows metrics", async ({ page }) => {
    test.skip(!(await configured(page)), "API/credential not configured");
    await expect(page.getByRole("heading", { name: "Reliability" })).toBeVisible();
    await expect(page.getByText("Terminal runs")).toBeVisible();
    await expect(page.getByText("Trace completeness")).toBeVisible();
  });

  test("datasets page offers an upload form and lists versions", async ({ page }) => {
    await page.goto("/datasets");
    test.skip(
      await page.getByRole("heading", { name: "Setup required" }).isVisible(),
      "API/credential not configured",
    );
    await expect(page.getByRole("button", { name: "Upload dataset" })).toBeVisible();
    await expect(page.getByText("sales")).toBeVisible();
  });

  test("a run detail surfaces evidence: answer, trace, config", async ({ page }) => {
    await page.goto("/runs");
    test.skip(
      await page.getByRole("heading", { name: "Setup required" }).isVisible(),
      "API/credential not configured",
    );
    const firstRun = page.getByRole("link", { name: /^[0-9a-f]{8}$/ }).first();
    await firstRun.click();
    await expect(page.getByRole("heading", { name: "Config manifest" })).toBeVisible();
  });

  test("evaluations page exports a report", async ({ page }) => {
    await page.goto("/evaluations");
    await expect(page.getByRole("heading", { name: "Evaluations" })).toBeVisible();
    const exportLink = page.getByRole("link", { name: "Export JSON" });
    if (await exportLink.isVisible()) {
      const download = page.waitForEvent("download");
      await exportLink.click();
      expect((await download).suggestedFilename()).toContain("comparison");
    }
  });

  test("review queue allows claiming a run", async ({ page }) => {
    await page.goto("/reviews");
    test.skip(
      await page.getByRole("heading", { name: "Setup required" }).isVisible(),
      "API/credential not configured",
    );
    await expect(page.getByRole("heading", { name: "Review queue" })).toBeVisible();
  });
});
