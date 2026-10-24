import { assertRoute, expect, logIn, startupLoader, test } from "./fixtures";
import {
  appSettings,
  catalogDetail,
  collection,
  collectionDetail,
  mediaItem,
} from "../helpers/fixtures";

test("default redirect opens shows when no movie libraries exist", async ({ page }) => {
  await page.route("**/api/library/libraries?*", (request) =>
    request.fulfill({
      json: request.request().url().includes("media_type=show")
        ? [{ id: "shows", title: "Shows", count: 1 }]
        : [],
    }),
  );
  await logIn(page);
  await assertRoute(page, "/shows");
  await expect(page.getByRole("button", { name: "Shows 1", exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

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
      route.fulfill({ json: appSettings({ media_server: "plex", collections_supported: true }) }),
    );
    await page.route("**/api/collections/1?*", (route) =>
      route.fulfill({ json: collectionDetail({ id: 1, title: "Action" }) }),
    );
    await page.route("**/api/collections?*", (route) =>
      route.fulfill({ json: [collection({ id: 1, title: "Action" })] }),
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

  test("unauthenticated cold deep link returns to the requested URL after login", async ({
    page,
  }) => {
    await page.goto("/movies/1-alien/themes");
    await expect(page.getByLabel("Password")).toBeVisible();
    await expect(page).toHaveURL(/\/login\?return_to=%2Fmovies%2F1-alien%2Fthemes$/);

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
    await expect(page).toHaveURL(/\/login\?return_to=%2Fmovies%2F1-alien%2Fthemes$/);

    await page.getByLabel("Password").fill("password");
    await page.getByRole("button", { name: "Sign In" }).click();
    await expect(startupLoader(page)).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Alien", exact: true })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Themes", selected: true })).toBeVisible();
    await assertRoute(page, "/movies/1-alien/themes");
  });
});

test("catalog deep links restore movie, show, season and collection views on reload", async ({
  page,
}) => {
  await page.route("**/api/public-dataset/catalog?*", (request) => request.fulfill({ json: [] }));
  await page.route("**/api/public-dataset/catalog/*/*", (request) => {
    const path = new URL(request.request().url()).pathname;
    const collection = path.includes("/collection/");
    const show = path.includes("/show/");
    return request.fulfill({
      json: catalogDetail({
        entry_key: collection ? "tmdb-10" : show ? "tvdb-81189" : "tmdb-348",
        entry: {
          ...catalogDetail().entry,
          media_type: collection ? "collection" : show ? "show" : "movie",
          title: collection ? "Star Wars" : show ? "Twin Peaks" : "Alien",
          tmdb_id: collection ? 10 : show ? null : 348,
          tvdb_id: show ? 81189 : null,
          seasons: show
            ? [{ season_num: 0, poster_url: "https://image.tmdb.org/t/p/original/zero.jpg" }]
            : null,
        },
      }),
    });
  });
  await logIn(page, "/overturedb/movies/tmdb-348/art/background");
  for (const [path, title, tab] of [
    ["/overturedb/movies/tmdb-348/art/background", "Alien", "Background"],
    ["/overturedb/shows/tvdb-81189", "Twin Peaks", "Poster"],
    ["/overturedb/shows/tvdb-81189/art/seasons/0", "Twin Peaks", "Seasons"],
    ["/overturedb/movies/collections/tmdb-10/themes", "Star Wars", "Themes"],
  ] as const) {
    await page.goto(path);
    await expect(page.getByRole("heading", { name: title, exact: true })).toBeVisible();
    await expect(page.getByRole("tab", { name: tab, selected: true })).toBeVisible();
    await assertRoute(page, path);
    await page.reload();
    await expect(page.getByRole("heading", { name: title, exact: true })).toBeVisible();
    await assertRoute(page, path);
  }
});

test("collection member rows show posters, link to items and omit show matching controls", async ({
  page,
}) => {
  const members = [
    mediaItem({
      id: 1,
      title: "Alien",
      year: 1979,
      poster_url: "https://image.tmdb.org/t/p/original/alien.jpg",
    }),
    mediaItem({
      id: 3,
      title: "Aliens",
      year: 1986,
      poster_url: "https://image.tmdb.org/t/p/original/aliens.jpg",
    }),
  ];
  const requestedPosters: string[] = [];
  await page.route("https://image.tmdb.org/**", (route) => {
    requestedPosters.push(route.request().url());
    return route.fulfill({
      contentType: "image/svg+xml",
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="2" height="3"/>',
    });
  });
  await page.route("**/api/settings", (route) =>
    route.fulfill({ json: appSettings({ collections_supported: true, tmdb_configured: true }) }),
  );
  await page.route("**/api/collections?*", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/collections/1?*", (route) =>
    route.fulfill({ json: collectionDetail({ id: 1, title: "Alien Collection", members }) }),
  );
  await page.route("**/api/collections/2?*", (route) =>
    route.fulfill({
      json: collectionDetail({ id: 2, title: "TV Collection", media_type: "show" }),
    }),
  );
  await logIn(page, "/movies/collections/1-alien-collection");
  await expect(page.getByRole("tab", { name: "Members", selected: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "TMDB collection match" })).toHaveCount(0);
  await page.getByRole("tab", { name: "Settings", exact: true }).click();
  await expect(page.getByRole("region", { name: "TMDB collection match" })).toBeVisible();
  await page.getByRole("tab", { name: "Members", exact: true }).click();
  const first = page.getByRole("button", { name: "Alien (1979)", exact: true });
  const second = page.getByRole("button", { name: "Aliens (1986)", exact: true });
  await first.scrollIntoViewIfNeeded();
  await expect(first).toBeVisible();
  await expect(second).toBeVisible();
  await expect
    .poll(() => requestedPosters)
    .toEqual(expect.arrayContaining(members.map((member) => member.poster_url)));
  const firstBox = await first.boundingBox();
  const secondBox = await second.boundingBox();
  expect(firstBox).not.toBeNull();
  expect(secondBox?.y).toBeGreaterThan(firstBox?.y ?? 0);
  await first.click();
  await assertRoute(page, "/movies/1-alien");

  await page.goto("/shows/collections/2-tv-collection");
  await expect(page.getByRole("heading", { name: "TV Collection", exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "Settings", exact: true }).click();
  await expect(page.getByRole("form", { name: "Collection settings", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "TMDB collection match" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Unmatch", exact: true })).toHaveCount(0);
});
