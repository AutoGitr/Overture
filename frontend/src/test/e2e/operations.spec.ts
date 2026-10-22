import { type Page } from "@playwright/test";
import { appSettings } from "../helpers/fixtures";
import { epoch, expect, logIn, realtimeSnapshot, test } from "./fixtures";

test("assets keeps every part of its results in place while downloads come and go", async ({
  page,
  realtime,
}) => {
  await page.route("**/api/settings", (route) =>
    route.fulfill({ json: appSettings({ art_download_workers: 2 }) }),
  );
  await logIn(page);
  let sequence = 0;
  const emit = (event: string, data: unknown) =>
    realtime.emit({ epoch, sequence: ++sequence, event, data });
  const emitRun = (status: "progress" | "completed", settled: number, log?: string) =>
    emit(`match.${status}`, {
      job: { kind: "bulk_art", status },
      total: 3,
      done: 3,
      queued: 3,
      settled,
      downloaded: settled,
      run_id: "run",
      log_total: settled + 1,
      ...(log && {
        log: { outcome: "Downloaded", target: log, reason: "written", at: "2026-01-01T12:00:00Z" },
      }),
    });
  const emitDownload = (id: string, title: string, status: "started" | "completed") =>
    emit(`download.${status}`, {
      job: {
        id,
        kind: "download",
        status,
        target: {
          target_type: "item",
          job_type: "art",
          media_item_id: 1,
          title,
          art_type: "poster",
        },
      },
    });

  emitRun("progress", 0, "Queued");
  emitDownload("first", "Alien", "started");
  emitDownload("second", "Brazil", "started");
  await page.getByRole("button", { name: "Assets", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Operations", exact: true });
  const art = dialog.getByRole("region", { name: "Art", exact: true });
  const log = art.getByRole("log");
  const downloads = art.getByRole("region", { name: "Downloads" });
  const rows = downloads.locator(".download-title");
  await expect(rows).toHaveText(["Alien", "Brazil"]);
  const dialogBox = await dialog.locator(".popup-content").boundingBox();
  const logBox = await log.boundingBox();
  const brazil = await rows.nth(1).boundingBox();

  // A finished download leaves its row idle; the next one takes that row.
  emitDownload("first", "Alien", "completed");
  emitRun("progress", 1, "Alien");
  await expect(rows).toHaveText(["Idle", "Brazil"]);
  expect(await rows.nth(1).boundingBox()).toEqual(brazil);
  expect(await log.boundingBox()).toEqual(logBox);

  emitDownload("third", "Casablanca", "started");
  await expect(rows).toHaveText(["Casablanca", "Brazil"]);
  expect(await rows.nth(1).boundingBox()).toEqual(brazil);
  expect(await log.boundingBox()).toEqual(logBox);
  await expect(art.getByTitle("Downloads waiting or still running")).toHaveText("queued: 2");

  emitDownload("second", "Brazil", "completed");
  emitDownload("third", "Casablanca", "completed");
  emitRun("completed", 3, "Casablanca");
  await expect(downloads).toHaveCount(0);
  await expect(art.getByTitle("Downloads waiting or still running")).toHaveText("queued: 0");
  await expect(dialog.getByRole("button", { name: "Clear Results" })).toBeVisible();
  // The popup fits its content, so only its bottom edge may move.
  const finalBox = await dialog.locator(".popup-content").boundingBox();
  expect([finalBox?.x, finalBox?.y, finalBox?.width]).toEqual([
    dialogBox?.x,
    dialogBox?.y,
    dialogBox?.width,
  ]);
});

test("the operations popup keeps its top edge and width across tabs and runs", async ({
  page,
  realtime,
}) => {
  await logIn(page);
  await page.getByRole("button", { name: "Assets", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Operations", exact: true });
  const content = dialog.locator(".popup-content");
  const edges = async () => {
    const box = await content.boundingBox();
    const viewport = page.viewportSize()!;
    expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height);
    return [box!.x, box!.y, box!.width];
  };
  const box = await edges();
  expect(box[1]).toBe(0);
  const tabs = dialog.getByRole("tablist", { name: "Operation modes" });
  const tabsBox = await tabs.boundingBox();
  const body = dialog.locator(".popup-body");
  for (const tab of ["Sync", "Renamer", "Server Audit", "Assets"]) {
    await dialog.getByRole("tab", { name: tab }).click();
    expect(await edges()).toEqual(box);
    expect(await tabs.boundingBox()).toEqual(tabsBox);
    expect(await body.evaluate((el) => el.scrollWidth - el.clientWidth)).toBe(0);
  }
  realtime.emit({
    epoch,
    sequence: 1,
    event: "sync.started",
    data: { job: { kind: "sync", status: "started" }, run_id: "run", log_total: 0 },
  });
  await dialog.getByRole("tab", { name: "Sync" }).click();
  await expect(dialog.getByRole("log")).toBeVisible();
  expect(await edges()).toEqual(box);
});

test("restart restores stopped results and active download blocks sync", async ({
  page,
  realtime,
}) => {
  const snapshot = {
    ...realtimeSnapshot,
    jobs: [
      {
        event: "match.stopped",
        data: {
          job: {
            kind: "bulk_art",
            status: "stopped",
            error: {
              message: "Interrupted by application restart or shutdown",
            },
          },
          done: 1,
          total: 3,
          started_at: "2026-01-01T00:00:00Z",
          finished_at: "2026-01-01T00:01:00Z",
        },
      },
    ],
  };
  realtime.setSnapshot(snapshot);
  await page.route("**/api/realtime/snapshot", (route) => route.fulfill({ json: snapshot }));
  await logIn(page);
  await page.getByRole("button", { name: "Assets", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Operations", exact: true });
  await expect(dialog.getByRole("tab", { name: /Assets/ }).locator(".tab-badge")).toHaveCount(0);
  await expect(dialog.getByText("Stopped", { exact: true })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Stop", exact: true })).toHaveCount(0);

  realtime.emit({
    epoch,
    sequence: 1,
    event: "download.started",
    data: {
      job: {
        id: "new-download",
        kind: "download",
        status: "started",
        target: {
          target_type: "item",
          job_type: "art",
          media_item_id: 1,
          title: "Alien",
          art_type: "poster",
        },
      },
    },
  });
  await dialog.getByRole("tab", { name: /Sync/ }).click();
  await expect(dialog.getByText("Wait for downloads to finish.")).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Run Now", exact: true })).toBeDisabled();
});

test("assets runs only the current sidebar search results", async ({ page }) => {
  await page.route("**/api/library/items?*", async (route) => {
    const movies = new URL(route.request().url()).searchParams.get("media_type") === "movie";
    await route.fulfill({
      json: {
        items: movies
          ? [
              {
                id: 1,
                title: "Alien",
                media_type: "movie",
                director: "Ridley Scott",
                monitored: false,
              },
              {
                id: 3,
                title: "Aliens",
                media_type: "movie",
                director: "James Cameron",
                monitored: true,
              },
            ]
          : [],
        total: movies ? 2 : 0,
      },
    });
  });
  let requestBody: unknown;
  await page.route("**/api/bulk/assets", async (route) => {
    requestBody = route.request().postDataJSON();
    await route.fulfill({ json: { art: "not_requested", themes: "started" } });
  });
  await logIn(page);
  await page.getByRole("button", { name: "Choose search field" }).click();
  await page.getByRole("menuitemradio", { name: "Director", exact: true }).click();
  await page.getByLabel("Search sidebar").fill("Ridley");
  await page.getByRole("button", { name: "Assets", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Operations", exact: true });
  await dialog.getByRole("checkbox", { name: "Current sidebar items 1 movie" }).check();
  await dialog
    .getByRole("region", { name: "Art", exact: true })
    .getByRole("checkbox", { name: "Enabled" })
    .uncheck();
  await expect(dialog.getByRole("button", { name: "Save Schedule" })).toBeDisabled();
  await dialog.getByRole("button", { name: "Run Now" }).click();
  await expect.poll(() => requestBody).toMatchObject({ library_ids: [], item_ids: [1], art: null });
});

async function openSidebarAssets(page: Page) {
  await page.getByRole("button", { name: "Assets", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Operations", exact: true });
  await dialog.getByRole("checkbox", { name: "Current sidebar items 1 movie" }).check();
  await dialog
    .getByRole("region", { name: "Art", exact: true })
    .getByRole("checkbox", { name: "Enabled" })
    .uncheck();
  return dialog;
}

test("a refused assets run never flashes the operations popup", async ({ page }) => {
  await page.route("**/api/bulk/assets", (route) =>
    route.fulfill({ status: 409, json: { detail: "Wait for full sync to finish" } }),
  );
  await logIn(page);
  const dialog = await openSidebarAssets(page);

  // Sample the popup on every frame from the click until the refusal shows.
  await page.evaluate(() => {
    const frames: string[] = [];
    (window as unknown as { frames_: string[] }).frames_ = frames;
    const sample = () => {
      const content = document.querySelector(".popup-content");
      const footer = document.querySelector(".popup-footer")?.textContent ?? "";
      if (content) frames.push(`${Math.round(content.getBoundingClientRect().height)}|${footer}`);
      if (!document.querySelector("[role=alert]")) requestAnimationFrame(sample);
    };
    requestAnimationFrame(sample);
  });
  await dialog.getByRole("button", { name: "Run Now" }).click();
  await expect(page.getByRole("alert")).toContainText("Wait for full sync to finish");
  const frames = await page.evaluate(() => (window as unknown as { frames_: string[] }).frames_);

  expect(frames.length).toBeGreaterThan(0);
  expect(new Set(frames).size).toBe(1);
  await expect(dialog.getByRole("button", { name: "Run Now" })).toBeEnabled();
});

test("assets waits for a running full sync and says why", async ({ page, realtime }) => {
  await logIn(page);
  realtime.emit({
    epoch,
    sequence: 1,
    event: "sync.started",
    data: { job: { kind: "sync", status: "running" }, total: 10 },
  });
  const dialog = await openSidebarAssets(page);
  await expect(dialog.getByRole("button", { name: "Run Now" })).toBeDisabled();
  await expect(dialog.getByText("Wait for the full sync to finish.")).toBeVisible();

  realtime.emit({
    epoch,
    sequence: 2,
    event: "sync.completed",
    data: { job: { kind: "sync", status: "completed" }, total: 10, done: 10 },
  });
  await expect(dialog.getByRole("button", { name: "Run Now" })).toBeEnabled();
  await expect(dialog.getByText("Wait for the full sync to finish.")).toHaveCount(0);
});
