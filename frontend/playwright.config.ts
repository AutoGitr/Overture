import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./src/test/e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: process.env.CI ? [["github"], ["list"]] : "list",
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    serviceWorkers: "block",
  },
  webServer: {
    command: "bun run preview -- --host 127.0.0.1 --port 5173 --strictPort",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: !process.env.CI,
    timeout: 120 * 1000,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
      testIgnore: "performance.spec.ts",
    },
    {
      name: "mobile-chrome",
      use: { ...devices["Pixel 7"] },
      testIgnore: "performance.spec.ts",
    },
    {
      // Budgets measure the page, so they run alone once every other test has
      // finished, not beside workers competing for the same CPU.
      name: "performance",
      use: { ...devices["Desktop Chrome"] },
      testMatch: "performance.spec.ts",
      fullyParallel: false,
      dependencies: ["chromium", "mobile-chrome"],
    },
  ],
});
