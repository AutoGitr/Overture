import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./src/test/oidc",
  // The tests reset one shared identity provider, so they run in order.
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? [["github"], ["list"]] : "list",
  use: {
    ...devices["Desktop Chrome"],
    baseURL: "http://127.0.0.1:8697",
    trace: "retain-on-failure",
    serviceWorkers: "allow",
  },
  webServer: {
    command:
      "uv run --project .. uvicorn tests.oidc_browser_server:app --app-dir .. --host 127.0.0.1 --port 8697 --no-access-log",
    url: "http://127.0.0.1:8697/api/auth/me",
    reuseExistingServer: false,
    timeout: 60000,
  },
});
