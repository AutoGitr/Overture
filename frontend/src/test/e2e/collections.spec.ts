import { expect, logIn, test } from "./fixtures";
import { appSettings, collectionDetail, collectionRule, mediaItem } from "../helpers/fixtures";

const first = mediaItem({ id: 1, title: "First", library_id: "movies", server_item_id: "m1" });
const second = mediaItem({ id: 2, title: "Second", library_id: "movies", server_item_id: "m2" });

test("a collection set previews and creates its collections without horizontal overflow", async ({
  page,
}) => {
  await page.route("**/api/settings", (route) =>
    route.fulfill({ json: appSettings({ media_server: "plex", collections_supported: true }) }),
  );
  await page.route("**/api/library/libraries?*", (route) =>
    route.fulfill({ json: [{ id: "movies", title: "Movies", count: 7 }] }),
  );
  await page.route("**/api/collections?*", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/collections/sets/preview", (route) =>
    route.fulfill({
      json: [
        {
          value: "1990",
          title: "1990s",
          member_count: 3,
          below_minimum: false,
          collection_id: null,
        },
        {
          value: "2000",
          title: "2000s",
          member_count: 1,
          below_minimum: true,
          collection_id: null,
        },
      ],
    }),
  );
  let saved: unknown = null;
  await page.route("**/api/collections/group-policy?*", (route) => {
    if (route.request().method() === "PUT") saved = route.request().postDataJSON();
    return route.fulfill({ json: saved ?? {} });
  });
  await page.route("**/api/collections/group-policy/sync?*", (route) =>
    route.fulfill({ json: { created: [13], removed: [], synced: 0, errors: {} } }),
  );
  await logIn(page, "/movies/collections/new");
  await expect(page.getByRole("button", { name: "Setup", exact: true })).toHaveAttribute(
    "aria-expanded",
    "true",
  );
  await expect(page.getByRole("button", { name: "Settings", exact: true })).toHaveAttribute(
    "aria-expanded",
    "false",
  );
  await page.getByText("One per value", { exact: true }).click();
  await page.getByLabel(/^Group/).fill("Decades");
  await page.getByRole("button", { name: "Preview collections", exact: true }).click();
  await expect(page.getByText("1 collection, 1 below the minimum.")).toBeVisible();
  await expect(page.locator("body")).toHaveJSProperty(
    "scrollWidth",
    await page.locator("body").evaluate((element) => element.clientWidth),
  );
  await page
    .getByRole("group", { name: "Save", exact: true })
    .getByRole("button", { name: "Save and Create", exact: true })
    .click();
  await expect
    .poll(() => saved)
    .toMatchObject({ generator: { dimension: "decade", library_ids: ["movies"] } });
  await expect(page).toHaveURL(/movies\/collections(\?|$)/);
});

test("collection members, metadata and rule views work on desktop and mobile", async ({ page }) => {
  // Append keeps members chosen by hand next to what the criteria match.
  const rule = collectionRule({ sync_mode: "append" });
  let detail = collectionDetail({
    id: 12,
    title: "Saga",
    library_id: "movies",
    child_count: 2,
    members: [first, second],
    rule,
    effective_sync_mode: "append",
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
  await page.route("**/api/collections/12/rule?*", (route) => route.fulfill({ json: rule }));
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
  // Save stays unavailable, and says why, until the form can be saved.
  await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
  await expect(page.getByRole("status").filter({ hasText: "Enter a title" })).toBeVisible();
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
  const views = page.getByRole("navigation", { name: "Configure sections" });
  await views.getByRole("link", { name: "Setup", exact: true }).click();
  await page.getByLabel("Title", { exact: true }).fill("Curated saga");
  await page
    .getByRole("group", { name: "Save", exact: true })
    .getByRole("button", { name: "Save", exact: true })
    .click();
  await expect(page.getByRole("heading", { name: "Curated saga", exact: true })).toBeVisible();
  await views.getByRole("link", { name: "Content", exact: true }).click();
  await expect(page.getByLabel("Sync mode", { exact: true })).toHaveValue("append");
  await page.getByRole("button", { name: "Condition", exact: true }).click();
  await page.getByLabel("Criteria condition 2 field", { exact: true }).selectOption("field:year");
  await page.getByLabel("Criteria condition 2 value", { exact: true }).fill("1990");
  await expect(page.getByRole("button", { name: "Save", exact: true })).toBeEnabled();
  const modes = page.getByRole("tablist", { name: "Detail modes", exact: true });
  const actions = page.getByRole("group", { name: "Record actions", exact: true });
  await expect(actions.getByRole("button")).toHaveCount(3);
  await expect(page.getByRole("region", { name: "Danger Zone", exact: true })).toHaveCount(0);
  const sections = page.locator(".detail-sections");
  const boxes = sections.locator(":scope > .tab-bar");
  await expect(boxes).toHaveCount(2);
  const lowerBox = await boxes.nth(1).boundingBox();
  await modes.getByRole("tab", { name: "Art", exact: true }).click();
  // Both rows keep their contents in every mode.
  await expect(views).toBeVisible();
  const categories = page.getByRole("tablist", { name: "Art categories", exact: true });
  await categories.getByRole("tab", { name: "Background", exact: true }).click();
  await expect(page).toHaveURL(/\/art\/background$/);
  await expect(page.getByRole("button", { name: "Paste URL & save as background" })).toBeVisible();
  await expect(categories.getByRole("tab", { name: "Background", selected: true })).toBeVisible();
  await modes.getByRole("tab", { name: "Themes", exact: true }).click();
  await expect(page.getByLabel("Search collection themes")).toBeVisible();
  await expect(categories.getByRole("tab", { selected: true })).toHaveCount(0);
  await expect(views).toBeVisible();
  await expect(boxes).toHaveCount(2);
  expect((await boxes.nth(1).boundingBox())?.height).toBe(lowerBox?.height);
  await expect(page.getByRole("button", { name: /^Paste URL/ })).toHaveCount(0);
  await expect(actions.getByRole("button")).toHaveCount(3);
  await modes.getByRole("tab", { name: "Configure", exact: true }).click();
  await views.getByRole("link", { name: "Content", exact: true }).click();
  await expect(page.getByLabel("Criteria condition 2 value", { exact: true })).toHaveValue("1990");
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
        rule: {
          criteria: {
            conditions: [
              { kind: "source", operator: "is", source: { type: "tmdb_list", list_ids: [123] } },
            ],
          },
        },
      });
      await route.fulfill({ json: detail });
    } else if (path === "/api/collections" || path === "/api/collections/groups")
      await route.fulfill({ json: [] });
    else if (path === "/api/collections/capabilities" || path === "/api/collections/presets")
      await route.fallback();
    else await route.fulfill({ json: detail });
  });
  await logIn(page);
  await page.goto("/movies/collections");
  await page.getByRole("button", { name: "Create collection", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "New collection", exact: true })).toBeVisible();
  await expect(page.getByRole("checkbox", { name: "Movies", exact: true })).toBeChecked();
  await expect(page.getByLabel(/^Start from/)).toBeInViewport();
  await page.getByLabel("Title", { exact: true }).fill("New collection");
  await page.getByRole("button", { name: "Condition", exact: true }).click();
  await page
    .getByLabel("Criteria condition 1 field", { exact: true })
    .selectOption("source:tmdb_list");
  await page.getByLabel("Criteria condition 1 TMDB list IDs", { exact: true }).fill("123");
  await page.getByRole("button", { name: "Save and Create", exact: true }).click();
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
    ["/movies/1-alien/art/poster", "Delete item from database"],
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
  const save = page.getByRole("button", { name: "Save", exact: true });
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
  await page.getByRole("button", { name: "Create collection", exact: true }).click();
  await expect(page.getByRole("checkbox", { name: "Other", exact: true })).not.toBeChecked();
  await page.getByLabel("Title", { exact: true }).fill("Unsaved collection");
  if (await page.getByRole("button", { name: "Toggle sidebar" }).isVisible())
    await page.getByRole("button", { name: "Toggle sidebar" }).click();
  await page.getByRole("button", { name: "Create collection", exact: true }).click();
  await expect(page.getByLabel("Title", { exact: true })).toHaveValue("");
  await expect(page.getByRole("checkbox", { name: "Other", exact: true })).not.toBeChecked();
});

test("a franchise set shares Setup and saves its library, group and schedule", async ({ page }) => {
  await page.route("**/api/settings", (route) =>
    route.fulfill({ json: appSettings({ media_server: "plex", collections_supported: true }) }),
  );
  await page.route("**/api/library/libraries?*", (route) =>
    route.fulfill({
      json: [
        { id: "movies", title: "Movies", count: 2 },
        { id: "other", title: "Other movies", count: 3 },
      ],
    }),
  );
  await page.route("**/api/collections/groups?*", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/collections?*", (route) => route.fulfill({ json: [] }));
  let saves = 0;
  let syncs = 0;
  await page.route("**/api/collections/group-policy?*", (route) => {
    if (route.request().method() === "PUT") {
      const body = route.request().postDataJSON();
      expect(body).toMatchObject({
        sync_schedule: "0 3 * * 0",
        visible_home: true,
        generator: {
          dimension: "franchise",
          library_ids: ["other"],
          strip_suffix: " Collection",
          exclude: ["10", "20"],
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
    return route.fulfill({ json: { created: [12], removed: [], synced: 0, errors: {} } });
  });
  await logIn(page, "/movies/collections/new");
  const setup = page.getByRole("region", { name: "Collection setup", exact: true });
  await setup.getByLabel("Title", { exact: true }).fill("Unsaved single collection");
  await setup.getByRole("checkbox", { name: "Other movies", exact: true }).check();
  await setup.getByText("One per value", { exact: true }).click();
  await expect(page.getByRole("navigation", { name: "Configure sections" })).toHaveCount(0);
  const submit = page.getByRole("button", { name: "Save and Create", exact: true });
  await page.getByLabel(/^Split by/).selectOption("franchise");
  // A blank group is named after what the set splits by.
  await expect(setup.getByLabel(/^Group/)).toHaveAttribute("placeholder", "TMDB franchises");
  await setup.getByLabel(/^Group/).fill("Franchises");
  await page.getByLabel("Trailing text to remove", { exact: true }).fill(" Collection");
  await page.getByLabel(/^Skip these values/).fill("10, 20");
  await page.getByRole("button", { name: "Schedule", exact: true }).click();
  await page.getByLabel("Sync schedule", { exact: true }).fill("0 3 * * 0");
  await setup.getByText("One collection", { exact: true }).click();
  await expect(setup.getByLabel("Title", { exact: true })).toHaveValue("Unsaved single collection");
  await setup.getByText("One per value", { exact: true }).click();
  await expect(page.getByLabel("Sync schedule", { exact: true })).toHaveValue("0 3 * * 0");
  await expect(page.locator("body")).toHaveJSProperty(
    "scrollWidth",
    await page.locator("body").evaluate((element) => element.clientWidth),
  );
  await submit.click();
  await expect.poll(() => new URL(page.url()).pathname).toBe("/movies/collections");
  await expect
    .poll(() => new URL(page.url()).searchParams.get("collection_group"))
    .toBe("group:Franchises");
  expect(saves).toBe(1);
  expect(syncs).toBe(1);
});

test("smart collections combine list sources and live criteria", async ({ page }) => {
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
  // Creating posts to the list's own URL, with ?to_server.
  await page.route("**/api/collections?*", (route) => {
    if (route.request().method() !== "POST") return route.fulfill({ json: [] });
    expect(route.request().postDataJSON()).toMatchObject({
      title: "Unwatched favorites",
      library_id: "movies",
      collection_filtering: "user",
      active_start_mmdd: "12-01",
      active_end_mmdd: "01-05",
      rule: {
        smart: true,
        criteria: {
          mode: "all",
          conditions: [
            {
              kind: "source",
              operator: "is",
              source: { type: "mdblist", identifiers: ["first/list", "second/list"] },
            },
            { kind: "field", field: "unplayed", operator: "is", value: true },
          ],
        },
      },
    });
    created = true;
    return route.fulfill({ json: detail });
  });
  await page.route("**/api/collections/12?*", (route) => route.fulfill({ json: detail }));
  await logIn(page, "/movies/collections/new");
  await page.getByLabel("Title", { exact: true }).fill("Unwatched favorites");
  await page.getByText("Plex (smart)", { exact: true }).click();
  await page.getByRole("button", { name: "Condition", exact: true }).click();
  await page
    .getByLabel("Criteria condition 1 field", { exact: true })
    .selectOption("source:mdblist");
  const lists = page.getByLabel("Criteria condition 1 MDBList lists", { exact: true });
  await lists.pressSequentially("first/list, second/list");
  await expect(lists).toHaveValue("first/list, second/list");
  await page.getByRole("button", { name: "Condition", exact: true }).click();
  await page
    .getByLabel("Criteria condition 2 field", { exact: true })
    .selectOption("field:unplayed");
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page
    .getByRole("combobox", { name: "Collection filtering", exact: true })
    .selectOption("user");
  await page.getByRole("button", { name: "Schedule", exact: true }).click();
  await page.getByLabel(/^Active from/).fill("12-01");
  await page.getByLabel(/^Active until/).fill("01-05");
  await expect(page.getByLabel("Search members", { exact: true })).toHaveCount(0);
  await expect(page.locator("body")).toHaveJSProperty(
    "scrollWidth",
    await page.locator("body").evaluate((element) => element.clientWidth),
  );
  const submit = page
    .getByRole("group", { name: "Save", exact: true })
    .getByRole("button", { name: "Save and Create", exact: true });
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
  // Save and Apply needs the group to hold a collection.
  await page.route("**/api/collections?*", (route) =>
    route.fulfill({ json: [collectionDetail({ id: 12, collection_group: "Weekend" })] }),
  );
  await logIn(page, "/movies/collections/new");
  await page.getByLabel("Title", { exact: true }).fill("Unsaved collection");
  const setup = page.getByRole("region", { name: "Collection setup", exact: true });
  await setup.getByLabel("Group", { exact: true }).selectOption("Weekend");
  // Groups are created and edited only in the popup.
  await setup.getByLabel("Group", { exact: true }).selectOption("Create new group...");
  await expect(setup.getByLabel("Group", { exact: true })).toHaveValue("Weekend");
  const dialog = page.getByRole("dialog", { name: "Collection groups" });
  await dialog.getByRole("combobox", { name: "Group", exact: true }).selectOption("Weekend");
  await dialog.getByRole("button", { name: "Settings", exact: true }).click();
  await dialog.getByRole("textbox", { name: "Sort title", exact: true }).fill("02_{title}");
  await expect(page.locator("body")).toHaveJSProperty(
    "scrollWidth",
    await page.locator("body").evaluate((element) => element.clientWidth),
  );
  await dialog.getByRole("button", { name: "Save and Apply", exact: true }).click();
  await expect(page.getByText("Saved and applied to 1 collection.")).toBeVisible();
  expect(applied).toBe(true);
  await dialog.getByRole("button", { name: "Close popup", exact: true }).click();
  await expect(page.getByLabel("Title", { exact: true })).toHaveValue("Unsaved collection");
});
