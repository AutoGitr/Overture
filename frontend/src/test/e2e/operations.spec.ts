import { type Page } from "@playwright/test";
import { epoch, expect, logIn, test } from "./fixtures";

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
  await dialog.getByRole("checkbox", { name: "Art", exact: true }).uncheck();
  await expect(dialog.getByRole("button", { name: "Save Schedule" })).toBeDisabled();
  await dialog.getByRole("button", { name: "Run Now" }).click();
  await expect.poll(() => requestBody).toMatchObject({ library_ids: [], item_ids: [1], art: null });
});

async function openSidebarAssets(page: Page) {
  await page.getByRole("button", { name: "Assets", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Operations", exact: true });
  await dialog.getByRole("checkbox", { name: "Current sidebar items 1 movie" }).check();
  await dialog.getByRole("checkbox", { name: "Art", exact: true }).uncheck();
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
