import { assertRoute, expect, logIn, test } from "./fixtures";
import { appSettings, catalogDetail, catalogEntry, catalogRow } from "../helpers/fixtures";

test("catalog seasons and sidebar use draft artwork and placeholders instead of TMDB images", async ({
  page,
  isMobile,
}) => {
  const original = "https://image.tmdb.org/t/p/original/catalog.jpg";
  const chosen = "https://image.tmdb.org/t/p/original/draft.jpg";
  let detail = catalogDetail({
    entry_key: "tmdb-1396",
    entry: catalogEntry({
      media_type: "show",
      tmdb_id: 1396,
      title: "Breaking Bad",
      poster_url: original,
      background_url: original,
      seasons: [{ season_num: 1, poster_url: original }],
    }),
  });
  detail.draft = {
    ...detail.entry,
    poster_url: chosen,
    background_url: null,
    seasons: [{ season_num: 1, poster_url: chosen }],
  };
  await page.route("https://image.tmdb.org/**", (route) =>
    route.fulfill({
      contentType: "image/svg+xml",
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="2" height="3"/>',
    }),
  );
  await page.route("**/api/settings", (route) =>
    route.fulfill({ json: appSettings({ tmdb_configured: true }) }),
  );
  await page.route("**/api/public-dataset/catalog?*", (route) =>
    route.fulfill({
      json: [catalogRow({ ...detail.entry, ...detail.draft, entry_key: detail.entry_key })],
    }),
  );
  await page.route("**/api/public-dataset/catalog/show/tmdb-1396", (route) =>
    route.fulfill({ json: detail }),
  );
  await page.route("**/api/public-dataset/catalog/show/tmdb-1396/draft", (route) => {
    detail = {
      ...detail,
      draft:
        route.request().method() === "DELETE"
          ? null
          : { ...detail.entry, ...route.request().postDataJSON() },
    };
    return route.fulfill({ json: detail });
  });
  await page.route("**/api/tmdb/show/1396", (route) =>
    route.fulfill({
      json: {
        ...detail.entry,
        poster_url: "https://image.tmdb.org/t/p/original/tmdb.jpg",
        background_url: "https://image.tmdb.org/t/p/original/tmdb-background.jpg",
        seasons: [0, 1, 2].map((season_num) => ({
          season_num,
          title: `Season ${season_num}`,
          poster_url: `https://image.tmdb.org/t/p/original/tmdb-season-${season_num}.jpg`,
        })),
      },
    }),
  );
  await logIn(page, "/overturedb/shows/tmdb-1396/art/seasons");
  const main = page.getByRole("main");
  await expect(main.getByRole("heading", { name: "Breaking Bad" })).toBeVisible();
  await expect(main.locator('img[src^="https://"]')).toHaveCount(2);
  await expect(main.locator(`img[src="${chosen}"]`)).toHaveCount(2);
  for (const season of [0, 2]) {
    const card = main.getByRole("button", { name: `Season ${season}`, exact: true });
    await expect(card).toBeVisible();
    await expect(card.locator("img")).toHaveCount(0);
  }
  await page.getByRole("button", { name: "Clear all art", exact: true }).click();
  await expect(main.locator(`img[src="${chosen}"]`)).toHaveCount(0);
  await expect(
    main.getByRole("button", { name: "Season 1", exact: true }).locator("img"),
  ).toHaveCount(0);
  if (isMobile) await page.getByLabel("Toggle sidebar").click();
  await expect(
    page.getByRole("link", { name: "Open poster for Breaking Bad in new tab" }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Select Breaking Bad", exact: true }).click();
  await page.getByRole("button", { name: "Discard draft", exact: true }).click();
  await page.getByRole("tab", { name: "Seasons", exact: true }).click();
  await expect(
    main.getByRole("button", { name: "Season 1", exact: true }).locator("img"),
  ).toHaveAttribute("src", original);
  await expect(main.locator('img[src*="tmdb-season-"]')).toHaveCount(0);
  if (isMobile) await page.getByLabel("Toggle sidebar").click();
  await expect(
    page.getByRole("link", { name: "Open poster for Breaking Bad in new tab" }),
  ).toHaveAttribute("href", original);
});

test("catalog collections use catalog member artwork and open members in OvertureDB", async ({
  page,
}) => {
  const poster = "https://image.tmdb.org/t/p/original/member-draft.jpg";
  await page.route("https://image.tmdb.org/**", (route) =>
    route.fulfill({
      contentType: "image/svg+xml",
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="2" height="3"/>',
    }),
  );
  await page.route("**/api/settings", (route) =>
    route.fulfill({ json: appSettings({ tmdb_configured: true }) }),
  );
  await page.route("**/api/public-dataset/catalog?*", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/public-dataset/catalog/collection/tmdb-10", (route) =>
    route.fulfill({
      json: catalogDetail({
        entry_key: "tmdb-10",
        entry: catalogEntry({ media_type: "collection", tmdb_id: 10, title: "Collection" }),
      }),
    }),
  );
  await page.route("**/api/tmdb/collection/10/art/poster/sources*", (route) =>
    route.fulfill({ json: { sources: {} } }),
  );
  await page.route("**/api/tmdb/collections/10?*", (route) => {
    expect(new URL(route.request().url()).searchParams.get("artwork_source")).toBe("overturedb");
    return route.fulfill({
      json: {
        tmdb_id: 10,
        title: "Collection",
        items: [
          {
            kind: "item",
            media_type: "movie",
            tmdb_id: 11,
            title: "Member",
            year: 2001,
            poster_url: poster,
            catalog_entry_key: "tmdb-11",
            existing_item_id: 9,
          },
          {
            kind: "item",
            media_type: "movie",
            tmdb_id: 12,
            title: "Missing poster",
            poster_url: null,
            existing_item_id: 8,
          },
        ],
      },
    });
  });
  await page.route("**/api/public-dataset/catalog/movie/tmdb-11", (route) =>
    route.fulfill({
      json: catalogDetail({
        entry_key: "tmdb-11",
        entry: catalogEntry({ tmdb_id: 11, title: "Member" }),
        draft: catalogEntry({ tmdb_id: 11, title: "Member", poster_url: poster }),
      }),
    }),
  );
  await page.route("**/api/tmdb/movie/11/art/poster/sources*", (route) =>
    route.fulfill({ json: { sources: {} } }),
  );
  await logIn(page, "/overturedb/movies/collections/tmdb-10/art/poster");
  const members = page.getByRole("region", { name: "Collection members" });
  const member = members.getByRole("button", { name: "Member (2001) In library" });
  await expect(member.locator("img")).toHaveAttribute("src", poster);
  await expect(
    members.getByRole("button", { name: "Missing poster In library" }).locator("img"),
  ).toHaveCount(0);
  await member.click();
  await assertRoute(page, "/overturedb/movies/tmdb-11");
  await expect(page.getByRole("heading", { name: "Member", exact: true })).toBeVisible();
  await expect(page.getByRole("main").locator(`img[src="${poster}"]`)).toHaveCount(1);
});
