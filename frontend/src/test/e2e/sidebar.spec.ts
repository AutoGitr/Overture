import { assertRoute, expect, logIn, test } from "./fixtures";
import {
  appSettings,
  catalogDetail,
  catalogEntry,
  catalogRow,
  collection,
  mediaItem,
} from "../helpers/fixtures";

test("sidebar row hit areas preserve selection, poster links, and badge actions", async ({
  page,
  context,
  isMobile,
}) => {
  const items = Array.from({ length: 100 }, (_, index) =>
    mediaItem({
      id: index + 1,
      title: `Movie ${String(index).padStart(3, "0")}`,
      server_item_id: "1",
    }),
  );
  await page.route("**/api/library/items?*", (route) =>
    route.fulfill({ json: { items, total: items.length } }),
  );
  await context.route("**/api/library/items/*/provider-**", (route) =>
    route.fulfill({
      contentType: "image/svg+xml",
      body: '<svg xmlns="http://www.w3.org/2000/svg"/>',
    }),
  );
  await page.route("**/api/themes/search?**", (route) => route.fulfill({ json: { results: [] } }));
  await page.route("**/api/public-dataset/items/*/sources", (route) =>
    route.fulfill({ json: { found: false, item: null, seasons: [] } }),
  );
  await logIn(page);
  const row = page.locator(".sidebar-item").filter({ hasText: "Movie 099" });
  await page.locator(".sidebar .virtual-list-wrapper").evaluate((element) => {
    element.scrollTop = element.scrollHeight;
  });
  await expect(row).toBeVisible();
  await page.getByLabel("Search sidebar").fill("Movie 099");
  await expect(row).toBeVisible();

  const poster = page.getByRole("link", { name: "Open poster for Movie 099 in new tab" });
  const popupPromise = page.waitForEvent("popup");
  await poster.click();
  const popup = await popupPromise;
  await popup.close();
  await assertRoute(page, "/movies");

  // Click padding, outside the title button's own box, using browser hit testing.
  await row.click({ position: { x: 3, y: 3 } });
  await assertRoute(page, "/movies/100-movie-099");
  if (isMobile) await page.getByLabel("Toggle sidebar").click();
  await page.getByRole("button", { name: "Open art for Movie 099" }).click();
  await assertRoute(page, "/movies/100-movie-099/art/poster");
  if (isMobile) await page.getByLabel("Toggle sidebar").click();
  await page.getByRole("button", { name: "Open themes for Movie 099" }).click();
  await assertRoute(page, "/movies/100-movie-099/themes");
  if (isMobile) await page.getByLabel("Toggle sidebar").click();
  await page.getByRole("button", { name: "Select Movie 099", exact: true }).focus();
  await page.keyboard.press("Enter");
  await assertRoute(page, "/movies/100-movie-099");
});

test("a collection theme badge opens its theme view", async ({ page }) => {
  await page.route("**/api/settings", (route) =>
    route.fulfill({ json: appSettings({ media_server: "plex", collections_supported: true }) }),
  );
  await page.route("**/api/collections?*", (route) =>
    route.fulfill({ json: [collection({ id: 1, title: "Action" })] }),
  );
  await page.route("**/api/themes/search?**", (route) => route.fulfill({ json: { results: [] } }));
  await logIn(page);
  await page.getByRole("button", { name: "Collections", exact: true }).click();
  const row = page.locator(".sidebar-item").filter({ hasText: "Action" });
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "Open themes for Action" }).click();
  await assertRoute(page, "/movies/collections/1-action/themes");
  await page.goBack();
  await assertRoute(page, "/movies/collections");
  await expect(row).toBeVisible();
});

test("a ten-thousand-item library stays virtualized and interactive", async ({ page }) => {
  const items = Array.from({ length: 10_000 }, (_, index) => ({
    id: index + 1,
    title: `Movie ${String(index).padStart(5, "0")}`,
    media_type: "movie",
    year: 2000 + (index % 25),
    monitored: true,
  }));
  await page.route("**/api/library/items*", async (route) => {
    const url = new URL(route.request().url());
    const mediaType = url.searchParams.get("media_type");
    if (mediaType !== "movie") return route.fallback();
    await route.fulfill({ json: { items, total: items.length } });
  });

  const loadStarted = Date.now();
  await logIn(page);
  await expect(page.getByRole("button", { name: "Select Movie 00000" })).toBeVisible();
  expect(Date.now() - loadStarted).toBeLessThan(8_000);
  expect(await page.locator('button[aria-label^="Select Movie "]').count()).toBeLessThan(100);

  const interactionStarted = Date.now();
  await page.getByLabel("Search sidebar").fill("Movie 09999");
  const last = page.getByRole("button", { name: "Select Movie 09999" });
  await expect(last).toBeVisible();
  await last.click();
  await expect(page.getByRole("heading", { name: "Movie 09999", exact: true })).toBeVisible();
  expect(Date.now() - interactionStarted).toBeLessThan(2_000);
});

test("catalog browsing filters drafts and saves and discards artwork on desktop and mobile", async ({
  page,
  isMobile,
}) => {
  let detail = catalogDetail({
    entry: catalogEntry({ poster_url: "https://image.tmdb.org/t/p/original/catalog.jpg" }),
    library_item_id: 1,
  });
  await page.route("https://image.tmdb.org/**", (route) =>
    route.fulfill({
      contentType: "image/svg+xml",
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="2" height="3"/>',
    }),
  );
  await page.route("**/api/settings", (route) =>
    route.fulfill({ json: appSettings({ tmdb_configured: true, auto_match_art: false }) }),
  );
  await page.route("**/api/public-dataset/catalog?*", (route) => {
    const type = new URL(route.request().url()).searchParams.get("media_type");
    return route.fulfill({
      json:
        type === "movie"
          ? [
              catalogRow({ ...(detail.draft ?? detail.entry), has_draft: !!detail.draft }),
              catalogRow({ entry_key: "tmdb-329865", title: "Arrival", tmdb_id: 329865 }),
            ]
          : [],
    });
  });
  await page.route("**/api/public-dataset/catalog/movie/tmdb-348", (route) =>
    route.fulfill({ json: detail }),
  );
  await page.route("**/api/public-dataset/catalog/movie/tmdb-348/draft", (route) => {
    detail = {
      ...detail,
      draft:
        route.request().method() === "DELETE"
          ? null
          : { ...(detail.draft ?? detail.entry), ...route.request().postDataJSON() },
    };
    return route.fulfill({ json: detail });
  });
  await page.route("**/api/tmdb/movie/348/art/poster/sources*", (route) =>
    route.fulfill({
      json: {
        sources: {
          tmdb: [
            {
              url: "https://image.tmdb.org/t/p/original/poster.jpg",
              art_type: "poster",
              source: "tmdb",
              width: 1000,
              height: 1500,
            },
          ],
        },
      },
    }),
  );
  await logIn(page);
  await page
    .getByRole("radiogroup", { name: "Sidebar source" })
    .getByText("OvertureDB", { exact: true })
    .click();
  await assertRoute(page, "/overturedb/movies");
  await expect(page.getByRole("button", { name: "Select Arrival", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Select Alien", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Alien", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "TMDB", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "OVERTUREDB", exact: true })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: /^(CATALOG|DRAFT)$/ })).toHaveCount(0);
  await expect(page.getByTitle("Contribute to OvertureDB", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Open in library", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Use artwork 1000x1500 from tmdb" }).click();
  await expect(page.getByRole("button", { name: "Discard draft" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "OVERTUREDB", exact: true })).toBeVisible();
  await expect(page.getByTitle("Contribute to OvertureDB", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Clear poster", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Clear artwork", exact: true })).toHaveCount(0);
  if (isMobile) await page.getByLabel("Toggle sidebar").click();
  await expect(
    page.getByRole("link", { name: "Open poster for Alien in new tab" }),
  ).toHaveAttribute("href", "https://image.tmdb.org/t/p/original/poster.jpg");
  await page.getByRole("button", { name: "Open filters" }).click();
  await expect(page.getByText("Monitor status", { exact: true })).toHaveCount(0);
  await page
    .getByRole("radiogroup", { name: "Has draft" })
    .getByText("Present", { exact: true })
    .click();
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page.getByRole("button", { name: "Select Alien", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Select Arrival", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Select Alien", exact: true }).click();
  await page.getByRole("button", { name: "Discard draft" }).click();
  await expect(page.getByRole("button", { name: "Discard draft" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "OVERTUREDB", exact: true })).toHaveCount(0);
  await expect(page.getByTitle("Contribute to OvertureDB", { exact: true })).toHaveCount(0);
  if (isMobile) await page.getByLabel("Toggle sidebar").click();
  await expect(page.getByText("No catalog entries found", { exact: true })).toBeVisible();
  await page
    .getByRole("radiogroup", { name: "Sidebar source" })
    .getByText("Library", { exact: true })
    .click();
  await assertRoute(page, "/movies");
  await expect(page.getByRole("button", { name: "Select Alien", exact: true })).toBeVisible();
});
