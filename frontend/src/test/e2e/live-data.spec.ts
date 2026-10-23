import { epoch, expect, logIn, realtimeSnapshot, test } from "./fixtures";

test("shows and clears OvertureDB sync feedback from realtime state", async ({
  page,
  realtime,
}) => {
  await logIn(page);

  await page.getByLabel("Open menu").click();
  const overtureDbButton = page.getByRole("button", { name: "OvertureDB", exact: true });
  await expect(overtureDbButton).toBeVisible();
  await overtureDbButton.click();
  await expect(page.getByRole("heading", { name: "OvertureDB", exact: true })).toBeVisible();

  const syncButton = page.getByRole("button", { name: "Sync OvertureDB Now", exact: true });
  await expect(syncButton).toBeEnabled();

  const syncRequest = page.waitForRequest(
    (request) =>
      request.method() === "POST" && new URL(request.url()).pathname === "/api/public-dataset/sync",
  );
  await syncButton.click();
  await syncRequest;

  await expect(page.getByRole("button", { name: "Syncing...", exact: true })).toBeDisabled();

  realtime.emit({
    epoch,
    sequence: 1,
    event: "public-dataset.sync.completed",
    data: {
      job: { kind: "public_dataset_sync", status: "completed" },
      finished_at: "2026-01-01T00:00:00+00:00",
    },
  });

  await expect(syncButton).toBeEnabled();
});

test("a failed initial library load is retryable and is not an empty library", async ({ page }) => {
  let fail = true;
  await page.route("**/api/library/items*", async (route) => {
    if (!fail || new URL(route.request().url()).searchParams.get("media_type") !== "movie")
      return route.fallback();
    await route.fulfill({
      status: 503,
      headers: { "X-Request-ID": "library-unavailable" },
      json: { detail: "Media server unavailable" },
    });
  });
  await logIn(page);
  await expect(
    page.getByText("Library unavailable. Use Retry in the notification to reconnect."),
  ).toBeVisible();
  await expect(page.getByText("No items found", { exact: true })).toHaveCount(0);
  fail = false;
  await page.getByRole("button", { name: "Retry Movies", exact: true }).click();
  await expect(page.getByRole("button", { name: "Select Alien", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Retry Movies", exact: true })).toHaveCount(0);
});

test("a failed background refresh keeps the last loaded library with a stale notice", async ({
  page,
  realtime,
}) => {
  await logIn(page);
  await expect(page.getByRole("button", { name: "Select Alien", exact: true })).toBeVisible();
  let fail = true;
  await page.route("**/api/library/items*", async (route) => {
    if (!fail || new URL(route.request().url()).searchParams.get("media_type") !== "movie")
      return route.fallback();
    await route.fulfill({ status: 503, json: { detail: "Media server unavailable" } });
  });
  realtime.emit({
    epoch,
    sequence: 1,
    event: "realtime.snapshot",
    data: { ...realtimeSnapshot, sequence: 1 },
  });
  await expect(page.getByRole("alert").filter({ hasText: "Couldn't load Movies" })).toContainText(
    "Showing last loaded data.",
  );
  await expect(page.getByRole("button", { name: "Select Alien", exact: true })).toBeVisible();
  fail = false;
  await page.getByRole("button", { name: "Retry Movies", exact: true }).click();
  await expect(page.getByRole("button", { name: "Retry Movies", exact: true })).toHaveCount(0);
});

test("failed live-data bootstrap is visible and a manual retry recovers it", async ({ page }) => {
  await page.routeWebSocket("**/ws", () => {});
  let available = false;
  await page.route("**/api/realtime/snapshot", async (route) => {
    await route.fulfill(
      available
        ? { json: realtimeSnapshot }
        : {
            status: 503,
            headers: { "X-Request-ID": "snapshot-unavailable" },
            json: { detail: "Snapshot unavailable" },
          },
    );
  });
  await logIn(page);
  await expect(page.getByRole("status").filter({ hasText: "snapshot-unavailable" })).toBeVisible();
  available = true;
  await page.getByRole("button", { name: "Retry live updates" }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "Live connection interrupted" }),
  ).toContainText("Updates are being checked periodically.");
  await expect(page.getByText("snapshot-unavailable", { exact: false })).toHaveCount(0);
});
