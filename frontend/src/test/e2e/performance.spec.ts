import type { Page } from "@playwright/test";
import { epoch, expect, logIn, test } from "./fixtures";
import { mediaItem } from "../helpers/fixtures";

const TITLES = 10_000;
/** The longest the page may stop responding; a frame every 50 ms feels instant. */
const LOAD_BUDGET_MS = 500;
const INTERACTION_BUDGET_MS = 300;
/** How long the page may take to apply a burst of live updates in total. */
const BURST_BUDGET_MS = 3_000;

declare global {
  interface Window {
    longestTask: number;
  }
}

async function watchLongTasks(page: Page) {
  await page.addInitScript(() => {
    window.longestTask = 0;
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        window.longestTask = Math.max(window.longestTask, entry.duration);
      }
    }).observe({ type: "longtask", buffered: true });
  });
}

const longestTask = (page: Page) => page.evaluate(() => window.longestTask);
const resetLongestTask = (page: Page) => page.evaluate(() => (window.longestTask = 0));
/** Long tasks are reported after they end, so let the last one arrive. */
const settle = (page: Page) =>
  page.evaluate(() => new Promise((resolve) => setTimeout(resolve, 250)));

const items = Array.from({ length: TITLES }, (_, index) =>
  mediaItem({ id: index + 1, title: `Movie ${String(index).padStart(5, "0")}` }),
);

test.beforeEach(async ({ page, isMobile }) => {
  test.skip(isMobile, "One device is enough to compare runs.");
  await watchLongTasks(page);
  await page.route("**/api/library/items?*", (route) =>
    route.fulfill({ json: { items, total: items.length } }),
  );
  await page.route("**/api/library/items/*/provider-**", (route) =>
    route.fulfill({
      contentType: "image/svg+xml",
      body: "<svg xmlns='http://www.w3.org/2000/svg'/>",
    }),
  );
  await logIn(page);
  await expect(page.locator(".sidebar-item").first()).toBeVisible();
  await settle(page);
});

test("a large library loads without freezing the page", async ({ page }) => {
  expect(await longestTask(page)).toBeLessThan(LOAD_BUDGET_MS);
});

test("searching a large library stays responsive", async ({ page }) => {
  await resetLongestTask(page);
  await page.getByLabel("Search sidebar").pressSequentially("Movie 09999", { delay: 20 });
  await expect(page.locator(".sidebar-item")).toHaveCount(1);
  await settle(page);
  expect(await longestTask(page)).toBeLessThan(INTERACTION_BUDGET_MS);
});

test("a burst of live updates keeps a large library responsive", async ({ page, realtime }) => {
  await resetLongestTask(page);
  const started = Date.now();
  for (let sequence = 1; sequence <= 300; sequence += 1) {
    realtime.emit({
      epoch,
      sequence,
      event: "library.item.upserted",
      data: { item: { ...items[sequence], monitored: false }, source: "match" },
    });
  }
  await settle(page);
  // The timer queues behind every update, so it resolves once all are applied.
  expect(Date.now() - started).toBeLessThan(BURST_BUDGET_MS);
  await settle(page);
  expect(await longestTask(page)).toBeLessThan(INTERACTION_BUDGET_MS);
});
