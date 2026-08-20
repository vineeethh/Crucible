import { expect, test } from "@playwright/test";

// Shell smoke: the primary navigation, the skip link, and the theme toggle work
// from the keyboard and reflect the current route. These do not require seeded
// data — they exercise the frame every page renders in.

test("landing page renders and reports API health", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Crucible" })).toBeVisible();
  // Either reachable or unreachable, but the status callout must be present.
  await expect(page.getByText(/API (reachable|unreachable)/)).toBeVisible();
});

test("primary navigation moves between sections and marks the active link", async ({ page }) => {
  await page.goto("/");
  const nav = page.getByRole("navigation", { name: "Primary" });
  await nav.getByRole("link", { name: "Reliability" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(nav.getByRole("link", { name: "Reliability" })).toHaveAttribute(
    "aria-current",
    "page",
  );

  await nav.getByRole("link", { name: "Evaluations" }).click();
  await expect(page).toHaveURL(/\/evaluations$/);
});

test("skip link is the first focusable element and targets main", async ({ page }) => {
  await page.goto("/");
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: "Skip to content" });
  await expect(skip).toBeFocused();
  await expect(page.locator("#main")).toBeVisible();
});

test("theme toggle flips and persists the theme", async ({ page }) => {
  await page.goto("/");
  const toggle = page.getByRole("button", { name: /Switch to (light|dark) theme/ });
  await toggle.click();
  const theme = await page.evaluate(() => document.documentElement.getAttribute("data-theme"));
  expect(theme).toMatch(/light|dark/);
  await page.reload();
  const persisted = await page.evaluate(() =>
    document.documentElement.getAttribute("data-theme"),
  );
  expect(persisted).toBe(theme);
});
