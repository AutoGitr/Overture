import { expect, logIn, test } from "./fixtures";
import { appSettings, collectionDetail, mediaItem } from "../helpers/fixtures";

const first = mediaItem({ id: 1, title: "First", library_id: "movies", server_item_id: "m1" });
const second = mediaItem({ id: 2, title: "Second", library_id: "movies", server_item_id: "m2" });

test("collection presets preview and create a selected set without horizontal overflow", async ({
  page,
}) => {
  await page.route("**/api/settings", (route) =>
    route.fulfill({ json: appSettings({ media_server: "plex", collections_supported: true }) }),
  );
  await page.route("**/api/library/libraries?*", (route) =>
    route.fulfill({ json: [{ id: "movies", title: "Movies", count: 7 }] }),
  );
  await page.route("**/api/collections?*", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/collections/presets/preview", (route) =>
    route.fulfill({
      json: [
        { key: "1990", title: "1990s", member_count: 3 },
        { key: "2000", title: "2000s", member_count: 4 },
      ],
    }),
  );
  let created = false;
  await page.route("**/api/collections/presets", (route) => {
    expect(route.request().postDataJSON()).toMatchObject({
      preset: "decades",
      library_id: "movies",
      keys: ["2000"],
    });
    created = true;
    return route.fulfill({ json: { collection_ids: [13], errors: {} } });
  });
  await logIn(page, "/movies/collections/new");
  await expect(page.getByRole("button", { name: "Collection Setup", exact: true })).toHaveAttribute(
    "aria-expanded",
    "true",
  );
  await expect(page.getByRole("button", { name: "Display", exact: true })).toHaveAttribute(
    "aria-expanded",
    "false",
  );
  await page.getByLabel("Type", { exact: true }).selectOption("preset");
  await expect(page.getByLabel("Preset", { exact: true })).toHaveValue("decades");
  await page.getByRole("button", { name: "Preview collections", exact: true }).click();
  await page.getByRole("checkbox", { name: "1990s (3 members)" }).uncheck();
  await expect(page.locator("body")).toHaveJSProperty(
    "scrollWidth",
    await page.locator("body").evaluate((element) => element.clientWidth),
  );
  await page
    .getByRole("group", { name: "Collection form actions" })
    .getByRole("button", { name: "Create selected collections" })
    .click();
  await expect(page).toHaveURL(/movies\/collections$/);
  expect(created).toBe(true);
});

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
  await page.route("**/api/collections/groups?*", (route) =>
    route.fulfill({ json: ["default-decades", "Weekend"] }),
  );
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
  const title = page.getByLabel("Title", { exact: true });
  await title.fill("");
  await page.getByRole("button", { name: "Collection Setup", exact: true }).click();
  await page.getByRole("button", { name: "Save Changes", exact: true }).click();
  await expect(title).toBeFocused();
  await title.fill("Saga");
  await page.getByRole("link", { name: "Members", exact: true }).click();
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
  const views = page.getByRole("group", { name: "Configure navigation" });
  await views.getByRole("link", { name: "Setup", exact: true }).click();
  await page.getByLabel("Title", { exact: true }).fill("Curated saga");
  await page
    .getByRole("group", { name: "Collection form actions", exact: true })
    .getByRole("button", { name: "Save", exact: true })
    .click();
  await expect(page.getByRole("heading", { name: "Curated saga", exact: true })).toBeVisible();
  await page.getByRole("combobox", { name: "Source", exact: true }).selectOption("builders");
  await views.getByRole("link", { name: "Content", exact: true }).click();
  await expect(page.getByLabel("Sync strategy")).toHaveValue("");
  await page.getByRole("button", { name: "Library filter", exact: true }).click();
  await page.getByRole("button", { name: "Condition", exact: true }).click();
  await page.getByLabel("Library filter group field 1", { exact: true }).selectOption("decade");
  await page.getByLabel("Library filter group value 1", { exact: true }).fill("1990");
  await expect(page.getByRole("button", { name: "Save Changes", exact: true })).toBeEnabled();
  const modes = page.getByRole("tablist", { name: "Detail modes", exact: true });
  const actions = page.getByRole("group", { name: "Record actions", exact: true });
  await expect(actions.getByRole("button")).toHaveCount(3);
  await expect(page.getByRole("region", { name: "Danger Zone", exact: true })).toHaveCount(0);
  const sections = page.locator(".detail-sections");
  const boxes = sections.locator(":scope > .tab-bar");
  await expect(boxes).toHaveCount(2);
  const lowerBox = await boxes.nth(1).boundingBox();
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
  await expect(boxes).toHaveCount(2);
  expect((await boxes.nth(1).boundingBox())?.height).toBe(lowerBox?.height);
  await page.getByRole("button", { name: "Search YouTube" }).click();
  await expect(page.getByLabel("Search collection themes")).toBeFocused();
  await expect(page.getByRole("button", { name: /^Paste URL/ })).toHaveCount(0);
  await expect(actions.getByRole("button")).toHaveCount(3);
  await modes.getByRole("tab", { name: "Configure", exact: true }).click();
  await views.getByRole("link", { name: "Content", exact: true }).click();
  await expect(page.getByLabel("Library filter group value 1", { exact: true })).toHaveValue(
    "1990",
  );
  await expect(page.locator("body")).toHaveJSProperty(
    "scrollWidth",
    await page.locator("body").evaluate((element) => element.clientWidth),
  );
});

test("collection creation uses the selected library and TMDB list sources", async ({ page }) => {
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
        member_ids: [],
        rule: { builders: [{ type: "tmdb_list", list_ids: [123] }] },
      });
      await route.fulfill({ json: detail });
    } else if (path === "/api/collections" || path === "/api/collections/groups")
      await route.fulfill({ json: [] });
    else await route.fulfill({ json: detail });
  });
  await logIn(page);
  await page.goto("/movies/collections");
  await page.getByRole("button", { name: "+ Create collection", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "New collection", exact: true })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Library", exact: true })).toHaveValue("movies");
  await expect(page.getByRole("combobox", { name: "Source", exact: true })).toBeInViewport();
  await page.getByLabel("Title", { exact: true }).fill("New collection");
  await page.getByRole("button", { name: "TMDB lists", exact: true }).click();
  await page.getByLabel("TMDB list IDs", { exact: true }).fill("123");
  await page.getByRole("button", { name: "Create collection", exact: true }).click();
  await expect(page).toHaveURL(/collections\/12-new-collection$/);
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
  await page.getByRole("link", { name: "Setup", exact: true }).click();
  await expect(page.getByLabel("Title", { exact: true })).toBeVisible();
  const save = page.getByRole("button", { name: "Save Changes" });
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

test("groups hide collections until opened, preserve browsing on asset navigation, and skip unidentified artwork candidates", async ({
  page,
}) => {
  const grouped = collectionDetail({
    id: 12,
    title: "Grouped saga",
    collection_group: "Weekend",
    members: [first],
    library_id: "movies",
  });
  const loose = collectionDetail({ id: 13, title: "Loose saga", members: [second] });
  let candidateRequests = 0;
  await page.route("**/api/settings", (route) =>
    route.fulfill({ json: appSettings({ media_server: "plex", collections_supported: true }) }),
  );
  await page.route("**/api/collections?*", (route) => route.fulfill({ json: [grouped, loose] }));
  await page.route("**/api/collections/12?*", (route) => route.fulfill({ json: grouped }));
  await page.route("**/api/collections/12/art/*/sources?*", (route) => {
    candidateRequests += 1;
    return route.fulfill({ json: { sources: {}, current_url: null } });
  });
  await logIn(page, "/movies/collections");
  await expect(page.getByRole("button", { name: "Open group Weekend" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Select collection Grouped saga" })).toHaveCount(0);
  await page.getByRole("button", { name: "Open group Weekend" }).click();
  await expect(page.getByRole("button", { name: "Select collection Grouped saga" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Select collection Loose saga" })).toHaveCount(0);
  await page.getByRole("button", { name: "Open art for Grouped saga" }).click();
  await expect(
    page.getByText(/Set a TMDB collection ID to browse artwork candidates/),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Background", exact: true }).click();
  await expect(
    page.getByText(/Set a TMDB collection ID to browse artwork candidates/),
  ).toBeVisible();
  expect(candidateRequests).toBe(0);
  await page.reload();
  if (await page.getByRole("button", { name: "Toggle sidebar" }).isVisible())
    await page.getByRole("button", { name: "Toggle sidebar" }).click();
  await expect(page.getByRole("button", { name: "Select collection Grouped saga" })).toBeVisible();
  await page.getByRole("button", { name: "Back to results" }).click();
  await expect(page.getByRole("button", { name: "Open group Weekend" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Select collection Grouped saga" })).toHaveCount(0);
});

test("creating again opens a fresh draft and multiple libraries require a choice", async ({
  page,
}) => {
  await page.route("**/api/settings", (route) =>
    route.fulfill({ json: appSettings({ media_server: "plex", collections_supported: true }) }),
  );
  await page.route("**/api/library/libraries?*", (route) =>
    route.fulfill({
      json: [
        { id: "movies", title: "Movies", count: 1 },
        { id: "other", title: "Other", count: 1 },
      ],
    }),
  );
  await page.route("**/api/collections?*", (route) => route.fulfill({ json: [] }));
  await logIn(page, "/movies/collections");
  await page.getByRole("button", { name: "+ Create collection", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Library", exact: true })).toHaveValue("");
  await page.getByLabel("Title", { exact: true }).fill("Unsaved collection");
  if (await page.getByRole("button", { name: "Toggle sidebar" }).isVisible())
    await page.getByRole("button", { name: "Toggle sidebar" }).click();
  await page.getByRole("button", { name: "+ Create collection", exact: true }).click();
  await expect(page.getByLabel("Title", { exact: true })).toHaveValue("");
  await expect(page.getByRole("combobox", { name: "Library", exact: true })).toHaveValue("");
});

test("franchise discovery shares Setup and submits its selected library and group", async ({
  page,
}) => {
  await page.route("**/api/settings", (route) =>
    route.fulfill({ json: appSettings({ media_server: "plex", collections_supported: true }) }),
  );
  await page.route("**/api/library/libraries?*", (route) =>
    route.fulfill({
      json: [
        { id: "movies", title: "Movies", count: 2 },
        { id: "other", title: "Other movies", count: 1 },
      ],
    }),
  );
  await page.route("**/api/collections?*", (route) => route.fulfill({ json: [] }));
  let saves = 0;
  let syncs = 0;
  await page.route("**/api/collections/group-policy?*", (route) => {
    if (route.request().method() === "PUT") {
      const body = route.request().postDataJSON();
      expect(body).toMatchObject({
        minimum_items: 2,
        sync_interval_hours: 168,
        visible_home: true,
        dynamic_tmdb: {
          enabled: true,
          library_id: "other",
          strip_suffix: " Collection",
          exclude_tmdb_ids: [10, 20],
        },
      });
      expect(new URL(route.request().url()).searchParams.get("name")).toBe("Franchises");
      saves++;
      return route.fulfill({ json: body });
    }
    return route.fulfill({ json: { visible_home: true } });
  });
  await page.route("**/api/collections/group-policy/sync?*", (route) => {
    syncs++;
    return route.fulfill({ json: { status: "ok" } });
  });
  await logIn(page, "/movies/collections/new");
  const setup = page.getByRole("region", { name: "Collection Setup", exact: true });
  await setup.getByLabel("Title", { exact: true }).fill("Unsaved single collection");
  await setup.getByRole("combobox", { name: "Library", exact: true }).selectOption("other");
  await setup.getByLabel("Type", { exact: true }).selectOption("preset");
  await setup.getByLabel("Preset", { exact: true }).selectOption("discovery");
  await expect(setup.getByLabel("Title", { exact: true })).toBeDisabled();
  await expect(page.getByRole("link", { name: "Display", exact: true })).toHaveCount(0);
  const submit = page.getByRole("button", { name: "Discover & Create Collections", exact: true });
  await expect(submit).toBeDisabled();
  await setup.getByLabel("Collection Group", { exact: true }).selectOption("__new__");
  await setup.getByLabel("New group name", { exact: true }).fill("Franchises");
  await page.getByLabel(/Exclude TMDB franchise IDs/).fill("10, 20");
  await page.getByRole("link", { name: "Schedule", exact: true }).click();
  await page.getByLabel("Sync interval (hours)", { exact: true }).fill("168");
  await page.getByRole("link", { name: "Setup", exact: true }).click();
  await setup.getByLabel("Type", { exact: true }).selectOption("custom");
  await expect(setup.getByLabel("Title", { exact: true })).toHaveValue("Unsaved single collection");
  await setup.getByLabel("Type", { exact: true }).selectOption("preset");
  await setup.getByLabel("Preset", { exact: true }).selectOption("discovery");
  await expect(page.getByLabel("Sync interval (hours)", { exact: true })).toHaveValue("168");
  await expect(page.locator("body")).toHaveJSProperty(
    "scrollWidth",
    await page.locator("body").evaluate((element) => element.clientWidth),
  );
  await submit.scrollIntoViewIfNeeded();
  await submit.click();
  await expect.poll(() => new URL(page.url()).pathname).toBe("/movies/collections");
  await expect
    .poll(() => new URL(page.url()).searchParams.get("collection_group"))
    .toBe("group:Franchises");
  expect(saves).toBe(1);
  expect(syncs).toBe(1);
});

test("smart collections combine list sources and live criteria from top to bottom", async ({
  page,
}) => {
  await page.route("**/api/settings", (route) =>
    route.fulfill({ json: appSettings({ media_server: "plex", collections_supported: true }) }),
  );
  await page.route("**/api/library/libraries?*", (route) =>
    route.fulfill({ json: [{ id: "movies", title: "Movies", count: 2 }] }),
  );
  const detail = collectionDetail({
    id: 12,
    title: "Unwatched favorites",
    library_id: "movies",
    kind: "smart",
  });
  let created = false;
  await page.route("**/api/collections*", (route) => {
    if (route.request().method() !== "POST") return route.fulfill({ json: [] });
    expect(route.request().postDataJSON()).toMatchObject({
      title: "Unwatched favorites",
      kind: "smart",
      library_id: "movies",
      member_ids: [],
      collection_filtering: "user",
      active_start_mmdd: "12-01",
      active_end_mmdd: "01-05",
      rule: {
        managed_label: "Favorites To Watch",
        builders: [{ type: "mdblist", identifiers: ["first/list", "second/list"] }],
        smart_filter: {
          filter_group: { conditions: [{ field: "unplayed", operator: "is", value: true }] },
        },
      },
    });
    created = true;
    return route.fulfill({ json: detail });
  });
  await page.route("**/api/collections/12?*", (route) => route.fulfill({ json: detail }));
  await logIn(page, "/movies/collections/new");
  await page.getByLabel("Title", { exact: true }).fill("Unwatched favorites");
  await page.getByLabel("Source", { exact: true }).selectOption("builders");
  await page.getByRole("button", { name: "MDBList", exact: true }).click();
  const lists = page.getByLabel("MDBList list URL or ID", { exact: true });
  await lists.pressSequentially("first/list, second/list");
  await expect(lists).toHaveValue("first/list, second/list");
  await page.getByLabel("Source", { exact: true }).selectOption("smart");
  await expect(lists).toHaveValue("first/list, second/list");
  const managedLabel = page.getByLabel(/Managed Plex label/);
  await managedLabel.pressSequentially("Favorites To Watch");
  await expect(managedLabel).toHaveValue("Favorites To Watch");
  await page.getByRole("button", { name: "Condition", exact: true }).click();
  await page
    .getByLabel("Smart collection criteria field 1", { exact: true })
    .selectOption("unplayed");
  await page.getByRole("link", { name: "Display", exact: true }).click();
  await page
    .getByRole("combobox", { name: "Collection filtering", exact: true })
    .selectOption("user");
  await page.getByRole("link", { name: "Schedule", exact: true }).click();
  await page.getByLabel(/^Active start/).fill("12-01");
  await page.getByLabel(/^Active end/).fill("01-05");
  await expect(page.getByLabel("Search members", { exact: true })).toHaveCount(0);
  await expect(page.getByLabel("Member order", { exact: true })).toHaveCount(0);
  await expect(page.locator("body")).toHaveJSProperty(
    "scrollWidth",
    await page.locator("body").evaluate((element) => element.clientWidth),
  );
  const submit = page
    .getByRole("group", { name: "Collection form actions", exact: true })
    .getByRole("button", { name: "Create", exact: true });
  await submit.scrollIntoViewIfNeeded();
  await submit.click();
  await expect(page).toHaveURL(/collections\/12-unwatched-favorites$/);
  expect(created).toBe(true);
});

test("group management saves and applies defaults separately from an unsaved collection", async ({
  page,
}) => {
  await page.route("**/api/settings", (route) =>
    route.fulfill({ json: appSettings({ media_server: "plex", collections_supported: true }) }),
  );
  await page.route("**/api/collections/groups?*", (route) => route.fulfill({ json: ["Weekend"] }));
  await page.route("**/api/collections/group-policy?*", (route) =>
    route.fulfill({
      json:
        route.request().method() === "PUT"
          ? route.request().postDataJSON()
          : { sort_title_format: "01_{title}", summary_format: null },
    }),
  );
  let applied = false;
  await page.route("**/api/collections/group-policy/apply?*", (route) => {
    applied = true;
    return route.fulfill({ json: { collection_ids: [12], errors: {} } });
  });
  await page.route("**/api/collections?*", (route) => route.fulfill({ json: [] }));
  await logIn(page, "/movies/collections/new");
  await page.getByLabel("Title", { exact: true }).fill("Unsaved collection");
  await page.getByLabel("Collection Group", { exact: true }).selectOption("Weekend");
  await page
    .getByRole("region", { name: "Collection Setup", exact: true })
    .getByRole("button", { name: "Manage groups", exact: true })
    .click();
  const dialog = page.getByRole("dialog", { name: "Collection groups" });
  await expect(dialog.getByRole("combobox", { name: "Group", exact: true })).toHaveValue("Weekend");
  await dialog.getByRole("button", { name: "Group settings", exact: true }).click();
  await dialog.getByRole("textbox", { name: /^Group sort title template/ }).fill("02_{title}");
  await expect(page.locator("body")).toHaveJSProperty(
    "scrollWidth",
    await page.locator("body").evaluate((element) => element.clientWidth),
  );
  await dialog.getByRole("button", { name: "Save & Apply to group", exact: true }).click();
  await expect(
    page.getByText("Group defaults applied to 1 collection. Explicit overrides were kept."),
  ).toBeVisible();
  expect(applied).toBe(true);
  await dialog.getByRole("button", { name: "Close popup", exact: true }).click();
  await expect(page.getByLabel("Title", { exact: true })).toHaveValue("Unsaved collection");
});
