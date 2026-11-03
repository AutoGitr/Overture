import { assertRoute, expect, logIn, test } from "./fixtures";

test.describe("service worker and PWA", () => {
  test.use({ serviceWorkers: "allow" });

  test("API and WebSocket namespace navigations bypass the cached app shell", async ({ page }) => {
    await page.goto("/");
    await page.evaluate(() => navigator.serviceWorker.ready);
    await page.waitForFunction(() => navigator.serviceWorker.controller !== null);

    await page.route(/\/(?:api|ws)(?:[/?]|$)/i, (route) => {
      if (!route.request().isNavigationRequest()) return route.fallback();
      return route.fulfill({ status: 404, json: { detail: "Not Found" } });
    });

    for (const path of [
      "/api",
      "/api?probe=1",
      "/api/missing?probe=1",
      "/API?probe=1",
      "/ws",
      "/ws?probe=1",
      "/ws/missing?probe=1",
      "/WS?probe=1",
    ]) {
      const response = await page.goto(path);
      expect(response?.fromServiceWorker(), path).toBe(false);
      expect(response?.status(), path).toBe(404);
      expect(await response?.json(), path).toEqual({ detail: "Not Found" });
    }
  });

  test("the installed app shell remains readable offline without caching the session", async ({
    page,
    context,
  }) => {
    const styleOrigins = new Set<string>();
    page.on("request", (request) => {
      if (["stylesheet", "font"].includes(request.resourceType()))
        styleOrigins.add(new URL(request.url()).origin);
    });
    await page.goto("/");
    await expect(page.getByLabel("Password")).toBeVisible();
    await page.evaluate(() => document.fonts.ready);
    await expect(page.locator("body")).toHaveCSS("font-size", "16px");
    await expect(page.locator("body")).toHaveCSS("font-family", /^Inter,/);
    expect(
      await page.evaluate(() =>
        [...document.fonts].some((font) => font.family === "Inter" && font.status === "loaded"),
      ),
    ).toBe(true);
    await page.evaluate(() => navigator.serviceWorker.ready);
    await page.waitForFunction(() => navigator.serviceWorker.controller !== null);
    expect([...styleOrigins]).toEqual([new URL(page.url()).origin]);
    await page.unroute("**/api/auth/me");
    await context.setOffline(true);
    await page.reload();
    await expect(page.getByRole("heading", { name: "Unable to connect" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Retry connection" })).toBeVisible();
    await expect(page.getByLabel("Password")).toHaveCount(0);
    await page.evaluate(() => document.fonts.ready);
    expect(
      await page.evaluate(() =>
        [...document.fonts].some((font) => font.family === "Inter" && font.status === "loaded"),
      ),
    ).toBe(true);
  });

  test("offline reload at a nested URL displays unable to connect", async ({ page, context }) => {
    await page.goto("/");
    await page.evaluate(() => navigator.serviceWorker.ready);
    await page.waitForFunction(() => navigator.serviceWorker.controller !== null);

    await logIn(page);
    await page.goto("/movies/1-alien");
    await expect(page.getByRole("heading", { name: "Alien", exact: true })).toBeVisible();
    await assertRoute(page, "/movies/1-alien");

    await page.unroute("**/api/auth/me");
    await context.setOffline(true);
    await page.reload();
    await expect(page.getByRole("heading", { name: "Unable to connect" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Retry connection" })).toBeVisible();
    await expect(page.getByLabel("Password")).toHaveCount(0);
    await assertRoute(page, "/movies/1-alien");
  });

  test("installed-app shortcuts open the selected library", async ({ page }) => {
    await logIn(page);
    const manifestUrl = await page.locator('link[rel="manifest"]').getAttribute("href");
    const manifest = await (await page.request.get(manifestUrl!)).json();
    for (const shortcut of manifest.shortcuts) {
      await page.goto(shortcut.url);
      await expect(
        page.getByRole("button", { name: new RegExp(`^${shortcut.name} `) }),
      ).toHaveAttribute("aria-pressed", "true");
      await assertRoute(page, shortcut.url);
    }
  });
});
