import { epoch, expect, logIn, realtimeSnapshot, test } from "./fixtures";

for (const hidden of [false, true]) {
  test(`startup completes with suspended animation frames (hidden=${hidden})`, async ({ page }) => {
    await page.route("**/api/auth/login", async (route) => {
      await page.evaluate((hidden) => {
        Object.defineProperty(document, "hidden", { configurable: true, value: hidden });
        window.requestAnimationFrame = () => 0;
      }, hidden);
      await route.fallback();
    });
    await logIn(page);
    await expect(page.getByRole("button", { name: "Select Alien", exact: true })).toBeVisible();
  });
}

test("an unavailable session shows a retry screen instead of a password prompt", async ({
  page,
}) => {
  let available = false;
  await page.route("**/api/auth/me", async (route) => {
    await route.fulfill(
      available
        ? { json: { authenticated: false } }
        : {
            status: 503,
            headers: { "X-Request-ID": "auth-unavailable" },
            json: { detail: "Service unavailable" },
          },
    );
  });
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText("auth-unavailable");
  await expect(page.getByLabel("Password")).toHaveCount(0);
  available = true;
  await page.getByRole("button", { name: "Retry connection" }).click();
  await expect(page.getByLabel("Password")).toBeVisible();
});

test("an expired API session closes the popup and permits a fresh sign-in", async ({
  page,
  realtime,
}) => {
  await logIn(page);
  await page.getByLabel("Open menu").click();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Settings" })).toBeVisible();
  let expired = true;
  let unauthorizedRequests = 0;
  await page.route("**/api/settings", async (route) => {
    if (!expired) return route.fallback();
    unauthorizedRequests++;
    await route.fulfill({ status: 401, json: { detail: "Session expired" } });
  });
  realtime.emit({
    epoch,
    sequence: 1,
    event: "realtime.snapshot",
    data: { ...realtimeSnapshot, sequence: 1 },
  });
  await expect(page.getByLabel("Password")).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Select Alien", exact: true })).toHaveCount(0);
  expect(unauthorizedRequests).toBe(1);
  expired = false;
  await page.getByLabel("Password").fill("password");
  await page.getByRole("button", { name: "Sign In" }).click();
  await expect(page.getByRole("button", { name: "Select Alien", exact: true })).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("a WebSocket authentication rejection ends the session", async ({ page, realtime }) => {
  await logIn(page);
  await realtime.close({ code: 4001, reason: "Session expired" });
  await expect(page.getByLabel("Password")).toBeVisible();
  await expect(page.getByLabel("Open menu")).toHaveCount(0);
});

test("failed logout checks the server before restoring the session and allows retry", async ({
  page,
}) => {
  let fail = true;
  await page.route("**/api/auth/logout", async (route) => {
    if (!fail) return route.fallback();
    await route.fulfill({
      status: 503,
      headers: { "X-Request-ID": "logout-unavailable" },
      json: { detail: "Service unavailable" },
    });
  });
  await logIn(page);
  await page.getByLabel("Open menu").click();
  await page.getByRole("button", { name: "Logout", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("logout-unavailable");
  await expect(page.getByLabel("Password")).toHaveCount(0);
  fail = false;
  await page.getByRole("button", { name: "Retry connection" }).click();
  await page.getByLabel("Open menu").click();
  await page.getByRole("button", { name: "Logout", exact: true }).click();
  await expect(page.getByLabel("Password")).toBeVisible();
});
