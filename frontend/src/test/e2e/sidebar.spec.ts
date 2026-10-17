import { assertRoute, expect, logIn, test } from "./fixtures";
import { collection, mediaItem } from "../helpers/fixtures";

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

test("a collection's decorative theme badge selects its row", async ({ page }) => {
  await page.route("**/api/settings", (route) =>
    route.fulfill({ json: { media_server: "plex", plex_collections_enabled: true } }),
  );
  await page.route("**/api/collections?*", (route) =>
    route.fulfill({ json: [collection({ id: "1", title: "Action" })] }),
  );
  await page.route("**/api/themes/search?**", (route) => route.fulfill({ json: { results: [] } }));
  await logIn(page);
  await page.getByRole("button", { name: "Collections", exact: true }).click();
  const row = page.locator(".sidebar-item").filter({ hasText: "Action" });
  await expect(row).toBeVisible();
  const badge = await row.locator(".item-badge").boundingBox();
  expect(badge).not.toBeNull();
  await page.mouse.click(badge!.x + badge!.width / 2, badge!.y + badge!.height / 2);
  await assertRoute(page, "/movies/collections/1-action");
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
