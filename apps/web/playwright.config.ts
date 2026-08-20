import { defineConfig, devices } from "@playwright/test";

// Critical-flow E2E tests. Runs against a locally built app on :3100.
//
// Requires the API + a seeded org (scripts/seed_demo.py) and browsers installed
// (`playwright install chromium`). Excluded from tsc/next build (see tsconfig)
// so the default gate never depends on Playwright being present.
const PORT = Number(process.env.WEB_PORT ?? 3100);
const BASE_URL = process.env.E2E_BASE_URL ?? `http://localhost:${PORT}`;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  // When E2E_BASE_URL is set the app is assumed already running (e.g. in CI);
  // otherwise Playwright starts a production build itself.
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : {
        command: `pnpm --filter web start --port ${PORT}`,
        url: BASE_URL,
        timeout: 120_000,
        reuseExistingServer: !process.env.CI,
      },
});
