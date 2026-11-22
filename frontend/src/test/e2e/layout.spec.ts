import type { LibrarySectionRead } from "../../generated/rest/types.gen";
import {
  appSettings,
  collectionDetail,
  collectionRule,
  logEntry,
  mediaServers,
} from "../helpers/fixtures";
import { epoch, expect, logIn, test } from "./fixtures";

/**
 * What the screen exposes when several servers are configured: every region a
 * view renders must be there, and none may lie under another. Accessibility
 * snapshots catch a missing or hidden region; the one screenshot catches what
 * only shows in the pixels.
 */

const SERVERS = mediaServers("plex", "jellyfin", "emby");
const [PLEX, JELLYFIN, EMBY] = SERVERS;

test.beforeEach(async ({ page }) => {
  await page.route("**/api/settings", (route) =>
    route.fulfill({
      json: appSettings({ workflow: "art", auto_match_art: false, media_servers: SERVERS }),
    }),
  );
});

test("a sync log about several servers offers a filter for each, above its lines", async ({
  page,
  realtime,
}) => {
  await logIn(page);
  const lines = [
    logEntry("Added", "Alien", "created in Movies with 3 titles", undefined, PLEX!),
    logEntry("Removed", "Alien", "deleted from Movies: a library left it", undefined, JELLYFIN!),
    logEntry("Unchanged", "Alien", "holds the same 3 titles in Movies", undefined, EMBY!),
  ];
  lines.forEach((log, index) =>
    realtime.emit({
      epoch,
      sequence: index + 1,
      event: index ? "sync.progress" : "sync.started",
      data: {
        job: { kind: "sync", status: index ? "progress" : "started" },
        run_id: "run",
        log,
        log_total: index + 1,
        log_outcomes: Object.fromEntries(lines.slice(0, index + 1).map((l) => [l.outcome, 1])),
        log_targets: Object.fromEntries(lines.slice(0, index + 1).map((l) => [l.outcome, 1])),
        log_servers: Object.fromEntries(
          lines.slice(0, index + 1).map((l) => [String(l.server_id), { [l.outcome]: 1 }]),
        ),
      },
    }),
  );
  await page.getByRole("button", { name: "Sync", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Operations", exact: true });
  await expect(dialog.getByRole("log")).toContainText("Unchanged");

  await expect(dialog.getByRole("tabpanel")).toMatchAriaSnapshot(`
    - group "Show log lines by outcome":
      - button "Added 1" [pressed]
      - button "Unchanged 1" [pressed]
      - button "Removed 1" [pressed]
    - group "Show log lines by media server":
      - button "Plex 1" [pressed]
      - button "Jellyfin 1" [pressed]
      - button "Emby 1" [pressed]
    - log "Job log"
  `);
  const filters = await dialog
    .getByRole("group", { name: "Show log lines by media server" })
    .boundingBox();
  const log = await dialog.getByRole("log").boundingBox();
  expect(filters!.y + filters!.height).toBeLessThanOrEqual(log!.y);
});

test("the filters popup chooses libraries of every server, or all of them at once", async ({
  page,
}) => {
  const libraries: LibrarySectionRead[] = SERVERS.map((server) => ({
    id: `${server.id}:movies`,
    title: "Movies",
    media_type: "movie",
    server_id: server.id,
    count: 3,
  }));
  await page.route("**/api/library/libraries{,?*}", (route) => route.fulfill({ json: libraries }));
  await logIn(page);
  await page.getByRole("button", { name: "Open filters" }).click();
  const dialog = page.getByRole("dialog", { name: "Filters & operations" });

  await expect(dialog).toMatchAriaSnapshot(`
    - checkbox "Select all libraries"
    - group "Plex":
      - checkbox "Movies"
    - group "Jellyfin":
      - checkbox "Movies"
    - group "Emby":
      - checkbox "Movies"
  `);
});

test("a collection's criteria name each library's server, edged in its colour", async ({
  page,
}) => {
  const libraries: LibrarySectionRead[] = [PLEX!, JELLYFIN!].map((server) => ({
    id: `${server.id}:movies`,
    title: "Movies",
    media_type: "movie",
    server_id: server.id,
    count: 3,
  }));
  const criteria = { mode: "all" as const, conditions: [], groups: [] };
  const rule = collectionRule({
    libraries: libraries.map((library) => ({ library_id: library.id, criteria })),
  });
  const detail = collectionDetail({
    id: 12,
    title: "Saga",
    library_ids: libraries.map((library) => library.id),
    rule,
  });
  await page.route("**/api/settings", (route) =>
    route.fulfill({
      json: appSettings({ media_servers: SERVERS, collections_supported: true }),
    }),
  );
  await page.route("**/api/library/libraries{,?*}", (route) => route.fulfill({ json: libraries }));
  await page.route("**/api/collections{,?*}", (route) => route.fulfill({ json: [detail] }));
  await page.route("**/api/collections/12{,?*}", (route) => route.fulfill({ json: detail }));
  await page.route("**/api/collections/12/rule{,?*}", (route) => route.fulfill({ json: rule }));
  await logIn(page);
  await page.goto("/collections/12-saga");
  await page
    .getByRole("navigation", { name: "Configure sections" })
    .getByRole("link", { name: "Content", exact: true })
    .click();

  await expect(page.locator("main")).toMatchAriaSnapshot(`
    - group "Plex Movies"
    - group "Jellyfin Movies"
  `);
  const edges = await page
    .locator("fieldset.criteria")
    .evaluateAll((sets) => sets.map((set) => getComputedStyle(set).borderInlineStartColor));
  expect(edges).toHaveLength(2);
  expect(edges[0]).not.toBe(edges[1]);
});

test("the sync panel looks as it should", async ({ page, realtime }, testInfo) => {
  test.skip(testInfo.project.name !== "chromium", "one browser's pixels are the reference");
  await logIn(page);
  realtime.emit({
    epoch,
    sequence: 1,
    event: "sync.started",
    data: {
      job: { kind: "sync", status: "started" },
      run_id: "run",
      log: logEntry("Added", "Alien", "created in Movies with 3 titles", undefined, PLEX!),
      log_total: 1,
      log_outcomes: { Added: 1 },
      log_targets: { Added: 1 },
      log_servers: { [String(PLEX!.id)]: { Added: 1 } },
    },
  });
  await page.getByRole("button", { name: "Sync", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Operations", exact: true });
  await expect(dialog.getByRole("log")).toContainText("Alien");
  await page.evaluate(() => document.fonts.ready);

  await expect(dialog.locator(".job-panel")).toHaveScreenshot("sync-panel.png", {
    animations: "disabled",
    mask: [dialog.locator("time"), dialog.locator(".job-stats")],
  });
});
