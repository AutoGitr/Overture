import { expect, logIn, test } from "./fixtures";
import { appSettings, collectionDetail, mediaItem } from "../helpers/fixtures";

const first = mediaItem({ id: 1, title: "First", library_id: "movies", server_item_id: "m1" });
const second = mediaItem({ id: 2, title: "Second", library_id: "movies", server_item_id: "m2" });

test("collection members, metadata and rule views work on desktop and mobile", async ({ page }) => {
  let detail = collectionDetail({
    id: 12,
    title: "Saga",
    library_id: "movies",
    child_count: 2,
    members: [first, second],
  });
  await page.route("**/api/settings", (route) =>
    route.fulfill({ json: appSettings({ media_server: "plex", collections_supported: true }) }),
  );
  await page.route("**/api/library/items?*", (route) =>
    route.fulfill({ json: { items: [first, second], total: 2 } }),
  );
  await page.route("**/api/collections?*", (route) => route.fulfill({ json: [detail] }));
  await page.route("**/api/collections/12?*", async (route) => {
    if (route.request().method() === "PUT")
      detail = { ...detail, ...route.request().postDataJSON() };
    await route.fulfill({ json: detail });
  });
  await page.route("**/api/collections/12/members?*", async (route) => {
    const body = route.request().postDataJSON();
    detail = {
      ...detail,
      members: body.member_ids.map((id: number) => (id === 1 ? first : second)),
      child_count: body.member_ids.length,
      order_type: body.order_type,
    };
    await route.fulfill({ json: detail });
  });
  await logIn(page);
  await page.goto("/movies/collections/12-saga");
  await page.getByRole("button", { name: "Move Second up", exact: true }).click();
  await expect(page.getByRole("listitem").first()).toContainText("Second");
  await page.getByRole("button", { name: "Remove First from collection" }).click();
  await expect(page.getByRole("listitem")).toHaveCount(1);
  const views = page.getByRole("navigation", { name: "Collection views" });
  await views.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByLabel("Title", { exact: true }).fill("Curated saga");
  await page.getByRole("button", { name: "Save collection settings" }).click();
  await expect(page.getByRole("heading", { name: "Curated saga", exact: true })).toBeVisible();
  await views.getByRole("button", { name: "Rule / Sync" }).click();
  await expect(page.getByLabel("Sync strategy")).toHaveValue("");
  await page.getByRole("combobox", { name: "Source", exact: true }).selectOption("filter");
  await page.getByLabel("Decade", { exact: true }).fill("1990");
  await expect(page.getByRole("button", { name: "Save rule", exact: true })).toBeEnabled();
  await expect(page.locator("body")).toHaveJSProperty(
    "scrollWidth",
    await page.locator("body").evaluate((element) => element.clientWidth),
  );
});

test("collection creation uses the selected library and members", async ({ page }) => {
  const detail = collectionDetail({
    id: 12,
    title: "New collection",
    library_id: "movies",
    members: [first],
    child_count: 1,
  });
  await page.route("**/api/settings", (route) =>
    route.fulfill({ json: appSettings({ media_server: "plex", collections_supported: true }) }),
  );
  await page.route("**/api/library/libraries?*", (route) =>
    route.fulfill({ json: [{ id: "movies", title: "Movies", count: 2 }] }),
  );
  await page.route("**/api/library/items?*", (route) =>
    route.fulfill({ json: { items: [first, second], total: 2 } }),
  );
  await page.route("**/api/collections*", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/collections" && route.request().method() === "POST") {
      expect(route.request().postDataJSON()).toMatchObject({
        title: "New collection",
        library_id: "movies",
        member_ids: [1],
      });
      await route.fulfill({ json: detail });
    } else if (path === "/api/collections") await route.fulfill({ json: [] });
    else await route.fulfill({ json: detail });
  });
  await logIn(page);
  await page.goto("/movies/collections");
  await page.getByRole("button", { name: "+ Create collection", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Create collection", exact: true });
  await dialog.getByLabel("Title", { exact: true }).fill("New collection");
  await dialog.getByRole("combobox", { name: "Library", exact: true }).selectOption("movies");
  await dialog.getByRole("checkbox", { name: "First", exact: true }).check();
  await dialog.getByRole("button", { name: "Create collection (1 members)" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "New collection", exact: true })).toBeVisible();
});

test("Emby collections clearly explain unsupported themes", async ({ page }) => {
  await page.route("**/api/settings", (route) =>
    route.fulfill({
      json: appSettings({
        media_server: "emby",
        collections_supported: true,
        collection_themes_unavailable: "Emby does not support collection themes",
      }),
    }),
  );
  await page.route("**/api/collections/12?*", (route) =>
    route.fulfill({
      json: collectionDetail({
        id: 12,
        title: "Emby saga",
        server_type: "emby",
        theme_unavailable: "Emby does not support collection themes",
      }),
    }),
  );
  await logIn(page);
  await page.goto("/movies/collections/12-emby-saga/themes");
  await expect(
    page.getByText("Emby does not support collection themes", { exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Search collection themes")).toHaveCount(0);
});
