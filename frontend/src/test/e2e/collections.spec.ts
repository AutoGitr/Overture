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
  await page.route("**/api/collections/12/art/*/sources?*", (route) =>
    route.fulfill({ json: { sources: {}, current_url: null } }),
  );
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
  await page.getByRole("button", { name: "Move First down", exact: true }).click();
  await expect(page.getByRole("listitem").first()).toContainText("Second");
  await page.getByRole("button", { name: "Move First up", exact: true }).click();
  await expect(page.getByRole("listitem").first()).toContainText("First");
  await page
    .getByRole("button", { name: "Drag First to reorder" })
    .dragTo(page.getByRole("listitem").nth(1));
  await expect(page.getByRole("listitem").first()).toContainText("Second");
  await page.getByRole("button", { name: "Remove First from collection" }).click();
  await expect(page.getByRole("listitem")).toHaveCount(1);
  const views = page.getByRole("tablist", { name: "Collection sections" });
  await views.getByRole("tab", { name: "Settings", exact: true }).click();
  await page.getByLabel("Title", { exact: true }).fill("Curated saga");
  await page.getByRole("button", { name: "Save collection settings" }).click();
  await expect(page.getByRole("heading", { name: "Curated saga", exact: true })).toBeVisible();
  await views.getByRole("tab", { name: "Rule / Sync" }).click();
  await expect(page.getByLabel("Sync strategy")).toHaveValue("");
  await page.getByRole("combobox", { name: "Source", exact: true }).selectOption("filter");
  await page.getByLabel("Decade", { exact: true }).fill("1990");
  await expect(page.getByRole("button", { name: "Save rule", exact: true })).toBeEnabled();
  const modes = page.getByRole("tablist", { name: "Detail modes", exact: true });
  const actions = page.getByRole("group", { name: "Record actions", exact: true });
  await expect(actions.getByRole("button")).toHaveCount(3);
  await modes.getByRole("tab", { name: "Art", exact: true }).click();
  await expect(views).toHaveCount(0);
  const categories = page.getByRole("tablist", { name: "Art categories", exact: true });
  await categories.getByRole("tab", { name: "Background", exact: true }).click();
  await expect(page).toHaveURL(/\/art\/background$/);
  await expect(page.getByRole("button", { name: "Paste URL & save as background" })).toBeVisible();
  await expect(categories.getByRole("tab", { name: "Background", selected: true })).toBeVisible();
  await modes.getByRole("tab", { name: "Themes", exact: true }).click();
  await expect(page.getByLabel("Search collection themes")).toBeVisible();
  await expect(categories).toHaveCount(0);
  await expect(page.getByRole("button", { name: /^Paste URL/ })).toHaveCount(0);
  await expect(actions.getByRole("button")).toHaveCount(3);
  await modes.getByRole("tab", { name: "Collection", exact: true }).click();
  await views.getByRole("tab", { name: "Rule / Sync", exact: true }).click();
  await expect(page.getByLabel("Decade", { exact: true })).toHaveValue("1990");
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

test("items and collections share record actions and fit a narrow viewport", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 800 });
  await page.route("**/api/settings", (route) =>
    route.fulfill({ json: appSettings({ media_server: "plex", collections_supported: true }) }),
  );
  await page.route("**/api/collections/12?*", (route) =>
    route.fulfill({ json: collectionDetail({ id: 12, title: "Saga", members: [first, second] }) }),
  );
  await logIn(page);
  for (const [path, deleteLabel] of [
    ["/movies/1-alien/art/poster", "Delete Item from Database"],
    ["/movies/collections/12-saga", "Delete collection"],
  ] as const) {
    await page.goto(path);
    const actions = page.getByRole("group", { name: "Record actions", exact: true });
    await expect(actions.getByRole("button")).toHaveCount(3);
    await expect(actions.getByRole("button").nth(0)).toHaveAttribute(
      "title",
      "Open Database Record",
    );
    await expect(actions.getByRole("button").nth(1)).toHaveAttribute(
      "title",
      /click to (unmonitor|monitor)$/,
    );
    await expect(actions.getByRole("button").nth(2)).toHaveAttribute("title", deleteLabel);
    await expect(page.locator("body")).toHaveJSProperty(
      "scrollWidth",
      await page.locator("body").evaluate((element) => element.clientWidth),
    );
  }
  await page.getByRole("tab", { name: "Settings", exact: true }).click();
  await expect(page.getByLabel("Title", { exact: true })).toBeVisible();
  const save = page.getByRole("button", { name: "Save collection settings" });
  await save.scrollIntoViewIfNeeded();
  await expect(save).toBeInViewport();
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
