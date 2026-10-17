import { assertRoute, expect, logIn, startupLoader, test } from "./fixtures";
import { collection } from "../helpers/fixtures";

test("selecting an item updates the URL path and survives a reload", async ({ page }) => {
  await logIn(page);

  const selectAlien = page.getByRole("button", { name: "Select Alien", exact: true });
  await expect(selectAlien).toBeVisible();
  await assertRoute(page, "/movies");

  await selectAlien.click();
  await expect(page.getByRole("heading", { name: "Alien", exact: true })).toBeVisible();
  await expect(page.getByTitle("Assets")).toBeVisible();
  await assertRoute(page, "/movies/1-alien");

  await page.reload();
  await expect(startupLoader(page)).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Alien", exact: true })).toBeVisible();
  await assertRoute(page, "/movies/1-alien");
});

test("switching libraries from an open item keeps the mobile sidebar visible", async ({
  page,
  isMobile,
}) => {
  test.skip(!isMobile, "Mobile-only navigation");
  await logIn(page);

  await page.getByRole("button", { name: "Select Alien", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Alien", exact: true })).toBeVisible();

  await page.getByLabel("Toggle sidebar").click();
  await page.getByRole("button", { name: /Shows/ }).click();

  await assertRoute(page, "/shows");
  await expect(page.getByRole("button", { name: "Select Twin Peaks", exact: true })).toBeVisible();
  await expect(page.getByText("Select a show from the sidebar")).toBeHidden();
});

test("an unavailable item retains its route and can be retried while live updates are unavailable", async ({
  page,
}) => {
  await logIn(page);
  await page.routeWebSocket("**/ws", () => {});
  await page.route("**/api/realtime/snapshot", (route) =>
    route.fulfill({ status: 503, json: { detail: "Live updates unavailable" } }),
  );
  let available = false;
  await page.route("**/api/library/items/99", async (route) => {
    await route.fulfill(
      available
        ? { json: { id: 99, title: "Arrival", media_type: "movie", monitored: true } }
        : { status: 503, json: { detail: "Item unavailable" } },
    );
  });
  await page.goto("/movies/99-arrival");
  await expect(startupLoader(page)).toHaveCount(0);
  await expect(page.getByRole("status").filter({ hasText: "Live updates failed" })).toContainText(
    "Live data may be out of date.",
  );
  const retryItem = page.getByRole("button", { name: "Retry item", exact: true });
  await expect(retryItem).toBeEnabled();
  await assertRoute(page, "/movies/99-arrival");
  available = true;
  await retryItem.click();
  await expect(page.getByRole("heading", { name: "Arrival", exact: true })).toBeVisible();
  await assertRoute(page, "/movies/99-arrival");
});

test.describe("path-based client routing", () => {
  test("default redirect replaces bare slash and unmatched paths with /movies", async ({
    page,
  }) => {
    await logIn(page);
    await page.goto("/");
    await expect(page.getByRole("button", { name: /^Movies / })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await assertRoute(page, "/movies");

    await page.goto("/unmatched/route/slug");
    await expect(page.getByRole("button", { name: /^Movies / })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await assertRoute(page, "/movies");
  });

  test("cold deep links to items, art tabs, themes, and collections restore view and path", async ({
    page,
  }) => {
    await page.route("**/api/settings", (route) =>
      route.fulfill({ json: { media_server: "plex", plex_collections_enabled: true } }),
    );
    await page.route("**/api/collections?*", (route) =>
      route.fulfill({ json: [collection({ id: "1", title: "Action" })] }),
    );
    await page.route("**/api/themes/search?**", (route) =>
      route.fulfill({ json: { results: [] } }),
    );
    await logIn(page);

    // Deep link directly to item
    await page.goto("/movies/1-alien");
    await expect(page.getByRole("heading", { name: "Alien", exact: true })).toBeVisible();
    await assertRoute(page, "/movies/1-alien");

    // Deep link to art poster subtab
    await page.goto("/movies/1-alien/art/poster");
    await expect(page.getByRole("heading", { name: "Alien", exact: true })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Art", selected: true })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Poster", selected: true })).toBeVisible();
    await assertRoute(page, "/movies/1-alien/art/poster");

    // Deep link to themes tab
    await page.goto("/movies/1-alien/themes");
    await expect(page.getByRole("heading", { name: "Alien", exact: true })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Themes", selected: true })).toBeVisible();
    await expect(page.locator(".theme-panel")).toBeVisible();
    await assertRoute(page, "/movies/1-alien/themes");

    // Deep link to collections list
    await page.goto("/movies/collections");
    await expect(page.getByRole("button", { name: "Collections", exact: true })).toBeVisible();
    await assertRoute(page, "/movies/collections");

    // Deep link to specific collection
    await page.goto("/movies/collections/1-action");
    await expect(page.getByRole("heading", { name: "Action", exact: true })).toBeVisible();
    await assertRoute(page, "/movies/collections/1-action");
  });

  test("unauthenticated cold deep link preserves requested URL through login", async ({ page }) => {
    // Navigate directly to deep URL while unauthenticated
    await page.goto("/movies/1-alien/themes");
    await expect(page.getByLabel("Password")).toBeVisible();
    await assertRoute(page, "/movies/1-alien/themes");

    // Sign in without redirecting away
    await page.getByLabel("Password").fill("password");
    await page.getByRole("button", { name: "Sign In" }).click();
    await expect(startupLoader(page)).toHaveCount(0);

    // Renders the requested view at the exact deep URL
    await expect(page.getByRole("heading", { name: "Alien", exact: true })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Themes", selected: true })).toBeVisible();
    await expect(page.locator(".theme-panel")).toBeVisible();
    await assertRoute(page, "/movies/1-alien/themes");
  });

  test("browser back and forward navigation restores view and exact pathname", async ({
    page,
    isMobile,
  }) => {
    await logIn(page);

    const selectAlien = page.getByRole("button", { name: "Select Alien", exact: true });
    await selectAlien.click();
    await expect(page.getByRole("heading", { name: "Alien", exact: true })).toBeVisible();
    await assertRoute(page, "/movies/1-alien");

    if (isMobile) await page.getByLabel("Toggle sidebar").click();
    await page.getByRole("button", { name: "Open themes for Alien" }).click();
    await expect(page.getByRole("tab", { name: "Themes", selected: true })).toBeVisible();
    await expect(page.locator(".theme-panel")).toBeVisible();
    await assertRoute(page, "/movies/1-alien/themes");

    await page.goBack();
    await expect(page.getByRole("heading", { name: "Alien", exact: true })).toBeVisible();
    await assertRoute(page, "/movies/1-alien");

    await page.goBack();
    await assertRoute(page, "/movies");

    await page.goForward();
    await expect(page.getByRole("heading", { name: "Alien", exact: true })).toBeVisible();
    await assertRoute(page, "/movies/1-alien");

    await page.goForward();
    await expect(page.getByRole("tab", { name: "Themes", selected: true })).toBeVisible();
    await expect(page.locator(".theme-panel")).toBeVisible();
    await assertRoute(page, "/movies/1-alien/themes");
  });

  test("browser refresh at a deep nested URL restores view and path", async ({ page }) => {
    await page.route("**/api/themes/search?**", (route) =>
      route.fulfill({ json: { results: [] } }),
    );
    await logIn(page);
    await page.goto("/movies/1-alien/themes");
    await expect(page.getByRole("heading", { name: "Alien", exact: true })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Themes", selected: true })).toBeVisible();
    await assertRoute(page, "/movies/1-alien/themes");

    await page.reload();
    await expect(startupLoader(page)).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Alien", exact: true })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Themes", selected: true })).toBeVisible();
    await assertRoute(page, "/movies/1-alien/themes");
  });

  test("session expiration at a deep URL preserves requested URL through re-login", async ({
    page,
    realtime,
  }) => {
    await page.route("**/api/themes/search?**", (route) =>
      route.fulfill({ json: { results: [] } }),
    );
    await logIn(page);
    await page.goto("/movies/1-alien/themes");
    await expect(page.getByRole("heading", { name: "Alien", exact: true })).toBeVisible();
    await assertRoute(page, "/movies/1-alien/themes");

    await realtime.close({ code: 4001, reason: "Session expired" });
    await expect(page.getByLabel("Password")).toBeVisible();
    await assertRoute(page, "/movies/1-alien/themes");

    await page.getByLabel("Password").fill("password");
    await page.getByRole("button", { name: "Sign In" }).click();
    await expect(startupLoader(page)).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Alien", exact: true })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Themes", selected: true })).toBeVisible();
    await assertRoute(page, "/movies/1-alien/themes");
  });
});
