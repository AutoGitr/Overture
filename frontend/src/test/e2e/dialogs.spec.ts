import { expect, logIn, test } from "./fixtures";
import { mediaItem } from "../helpers/fixtures";

test("the ID mismatch issue shows only items whose catalog IDs differ", async ({ page }) => {
  await page.route("**/api/library/items?*", (request) =>
    request.fulfill({
      json: {
        items: [
          mediaItem({ id: 1, title: "Mismatch", public_dataset_ids: "mismatching" }),
          mediaItem({ id: 2, title: "Matching", public_dataset_ids: "matching" }),
        ],
        total: 2,
      },
    }),
  );
  await logIn(page);
  await page.getByRole("button", { name: "Open filters" }).click();
  await page
    .getByRole("region", { name: "Metadata issues" })
    .getByRole("checkbox", { name: "ID mismatch" })
    .check();
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page.getByRole("button", { name: "Select Mismatch", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Select Matching", exact: true })).toHaveCount(0);
});

test("dropdown borders follow the accent colour", async ({ page }) => {
  await logIn(page);
  const accent = "rgb(72, 164, 218)";
  await page.evaluate((colour) => {
    document.documentElement.style.setProperty("--accent", colour);
  }, accent);

  await page.getByRole("button", { name: "Choose search field" }).click();
  await expect(page.getByRole("menu", { name: "Search by" })).toHaveCSS("border-color", accent);
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Choose sort order" }).click();
  await expect(page.getByRole("menu", { name: "Sort by" })).toHaveCSS("border-color", accent);
  await page.keyboard.press("Escape");
  await page.getByLabel("Open menu").click();
  await expect(page.locator(".menu-dropdown")).toHaveCSS("border-color", accent);
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Aspect ratio control" })).toHaveCSS(
    "border-color",
    accent,
  );
});

test("filter range limits share a row without overflowing", async ({ page }) => {
  await logIn(page);
  await page.getByRole("button", { name: "Open filters" }).click();
  const dialog = page.getByRole("dialog", { name: "Filters & operations" });
  await expect(dialog).toBeVisible();
  await page.evaluate(() => document.fonts.ready);

  for (const range of ["width (px)", "length (s)"]) {
    const min = dialog.getByRole("spinbutton", { name: `Min ${range}` });
    const max = dialog.getByRole("spinbutton", { name: `Max ${range}` });
    await min.scrollIntoViewIfNeeded();
    await expect(min).toBeVisible();
    await expect(max).toBeVisible();
    const minBox = await min.boundingBox();
    const maxBox = await max.boundingBox();
    expect(minBox).not.toBeNull();
    expect(maxBox).not.toBeNull();
    expect(minBox!.y).toBeCloseTo(maxBox!.y, 0);
    expect(minBox!.x + minBox!.width).toBeLessThan(maxBox!.x);
    expect(maxBox!.x + maxBox!.width).toBeLessThanOrEqual(page.viewportSize()!.width);
  }
});

test("dialogs isolate keyboard focus and restore the opener", async ({ page }) => {
  await logIn(page);
  const opener = page.getByLabel("Open menu");
  await opener.click();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Settings" });
  await expect(dialog).toBeVisible();
  await expect(dialog).toHaveAttribute("aria-modal", "true");
  const close = dialog.getByRole("button", { name: "Close popup" });
  await expect(close).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(dialog.getByLabel("Aspect ratio control")).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(close).toBeFocused();
  // Native dialogs allow access to browser controls, but not background content.
  await page.keyboard.press("Shift+Tab");
  await expect(opener).not.toBeFocused();
  await page.keyboard.press("Tab");
  await expect(close).toBeFocused();
  await opener.evaluate((button: HTMLButtonElement) => button.focus());
  await expect(close).toBeFocused();
  await page.evaluate(() => document.fonts.ready);
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(opener).toBeFocused();
});

test("toolbar dialogs restore focus and stay inside the viewport", async ({ page }) => {
  await logIn(page);
  const opener = page.getByRole("button", { name: "Assets", exact: true });
  await opener.click();
  const dialog = page.getByRole("dialog", { name: "Operations", exact: true });
  await expect(dialog).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  const box = await dialog.locator(".popup-content").boundingBox();
  const viewport = page.viewportSize()!;
  expect(box).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.y).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width);
  expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height);
  await dialog.getByRole("button", { name: "Close popup" }).click();
  await expect(opener).toBeFocused();
});

test("filters dialog stays inside the viewport and scrolls its body", async ({ page }) => {
  await page.route("**/api/library/libraries?*", (route) =>
    route.fulfill({
      json: [
        { id: 1, title: "Movies", count: 3500 },
        { id: 2, title: "4K Movies", count: 261 },
      ],
    }),
  );
  await logIn(page);
  const opener = page.getByRole("button", { name: "Open filters", exact: true });
  await opener.click();
  const dialog = page.getByRole("dialog", { name: "Filters & operations", exact: true });
  await expect(dialog).toBeVisible();
  await page.evaluate(() => document.fonts.ready);

  const viewport = page.viewportSize()!;
  const content = dialog.locator(".popup-content");
  const header = dialog.locator(".popup-header");
  const footer = dialog.locator(".popup-footer");
  const body = dialog.locator(".popup-body");

  // Initial bounds check: whole popup, header and footer must fit inside viewport
  let box = await content.boundingBox();
  let headerBox = await header.boundingBox();
  let footerBox = await footer.boundingBox();
  expect(box).not.toBeNull();
  expect(headerBox).not.toBeNull();
  expect(footerBox).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.y).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width);
  expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height);
  expect(headerBox!.y).toBeGreaterThanOrEqual(0);
  expect(footerBox!.y + footerBox!.height).toBeLessThanOrEqual(viewport.height);

  // Overlay dialog itself must not be scrollable
  await dialog.evaluate((el: HTMLElement) => {
    el.scrollTop = 500;
  });
  const dialogScroll = await dialog.evaluate((el: HTMLElement) => el.scrollTop);
  expect(dialogScroll).toBe(0);

  // Popup body should scroll internally while header and footer remain pinned in-bounds
  await body.evaluate((el: HTMLElement) => {
    el.scrollTop = el.scrollHeight;
  });
  const bodyScroll = await body.evaluate((el: HTMLElement) => el.scrollTop);
  expect(bodyScroll).toBeGreaterThan(0);

  box = await content.boundingBox();
  headerBox = await header.boundingBox();
  footerBox = await footer.boundingBox();
  expect(box!.y).toBeGreaterThanOrEqual(0);
  expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height);
  expect(headerBox!.y).toBeGreaterThanOrEqual(0);
  expect(footerBox!.y + footerBox!.height).toBeLessThanOrEqual(viewport.height);

  // Focus an input inside the body; popup header and footer must remain inside viewport
  const minInput = dialog.getByLabel("Min width (px)");
  await minInput.focus();
  box = await content.boundingBox();
  headerBox = await header.boundingBox();
  footerBox = await footer.boundingBox();
  expect(box!.y).toBeGreaterThanOrEqual(0);
  expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height);
  expect(headerBox!.y).toBeGreaterThanOrEqual(0);
  expect(footerBox!.y + footerBox!.height).toBeLessThanOrEqual(viewport.height);

  await dialog.getByRole("button", { name: "Close popup" }).click();
  await expect(opener).toBeFocused();
});

test("settings cannot be saved until their server values have loaded", async ({ page }) => {
  let available = false;
  await page.route("**/api/settings", async (route) => {
    if (!available) return route.fulfill({ status: 503, json: { detail: "Settings unavailable" } });
    await route.fulfill({ json: { workflow: "themes", auto_match_art: false } });
  });
  await logIn(page);
  await page.getByLabel("Open menu").click();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Settings" });
  await expect(dialog.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
  await expect(dialog.getByLabel("Workflow")).toBeDisabled();
  await expect(dialog.getByRole("button", { name: "Retry settings", exact: true })).toBeEnabled();
  available = true;
  await dialog.getByRole("button", { name: "Retry settings", exact: true }).click();
  await expect(dialog.getByLabel("Workflow")).toHaveValue("themes");
  await expect(dialog.getByRole("button", { name: "Save", exact: true })).toBeEnabled();
});

test("all popups stay strictly inside the viewport and prevent overlay scrolling", async ({
  page,
}) => {
  await page.route(/\/api\/backups/, (route) => {
    if (route.request().url().includes("/schedule")) {
      return route.fulfill({
        json: {
          enabled: false,
          cron_expression: "0 0 * * *",
          retention: null,
          timezone: "UTC",
        },
      });
    }
    return route.fulfill({ json: { backups: [] } });
  });
  await page.route(/\/api\/public-dataset\/status/, (route) =>
    route.fulfill({
      json: {
        enabled: false,
        last_sync: null,
        last_stats: null,
        timezone: "UTC",
      },
    }),
  );
  await page.route("**/api/stats", (route) =>
    route.fulfill({
      json: {
        storage: {
          artwork_size_bytes: 1000,
          themes_size_bytes: 1000,
          database_size_bytes: 1000,
          backups_size_bytes: 1000,
          total_footprint_bytes: 4000,
        },
      },
    }),
  );
  await logIn(page);
  const viewport = page.viewportSize()!;

  const popupsToTest = [
    { menuName: "Settings", dialogTitle: "Settings" },
    { menuName: "Backup", dialogTitle: "Backup" },
    { menuName: "Statistics", dialogTitle: "Statistics" },
    { menuName: "OvertureDB", dialogTitle: "OvertureDB" },
  ];

  for (const { menuName, dialogTitle } of popupsToTest) {
    await page.getByLabel("Open menu").click();
    await page.getByRole("button", { name: menuName, exact: true }).click();
    const dialog = page.getByRole("dialog", { name: dialogTitle, exact: true });
    await expect(dialog).toBeVisible();
    await page.evaluate(() => document.fonts.ready);

    const content = dialog.locator(".popup-content");
    const header = dialog.locator(".popup-header");
    const box = await content.boundingBox();
    const headerBox = await header.boundingBox();

    expect(box).not.toBeNull();
    expect(headerBox).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.y).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width);
    expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height);
    expect(headerBox!.y).toBeGreaterThanOrEqual(0);
    // Width keeps a gutter; height may fill the screen and remains centered.
    expect(box!.x).toBeGreaterThan(0);
    expect(box!.x + box!.width).toBeLessThan(viewport.width);
    expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height);
    expect(box!.y + box!.height / 2).toBeCloseTo(viewport.height / 2, 0);
    const body = dialog.locator(".popup-body");
    expect(await body.evaluate((el) => el.scrollWidth - el.clientWidth)).toBe(0);

    // Verify dialog overlay is not scrollable
    await dialog.evaluate((el: HTMLElement) => {
      el.scrollTop = 500;
    });
    const dialogScroll = await dialog.evaluate((el: HTMLElement) => el.scrollTop);
    expect(dialogScroll).toBe(0);

    await dialog.getByRole("button", { name: "Close popup" }).click();
    await expect(dialog).toHaveCount(0);
  }
});

test("a confirmation stays a small dialog on every screen", async ({ page }) => {
  await logIn(page);
  await page.getByRole("button", { name: "Open filters" }).click();
  await page.getByRole("button", { name: /^Delete from Overture/ }).click();
  const confirm = page.getByRole("dialog", { name: /^Delete 1 filtered/ });
  await expect(confirm).toBeVisible();

  const box = (await confirm.locator(".popup-content").boundingBox())!;
  const viewport = page.viewportSize()!;
  expect(box.x).toBeGreaterThan(0);
  expect(box.x + box.width).toBeLessThan(viewport.width);
  expect(box.height).toBeLessThan(viewport.height / 2);
  await confirm.getByRole("button", { name: "Cancel" }).click();
  await expect(confirm).toHaveCount(0);
});

test("short screens give popups their full safe height and scroll content behind fixed controls", async ({
  page,
}) => {
  await page.setViewportSize({ width: 640, height: 320 });
  await logIn(page);
  await page.evaluate(() => {
    document.documentElement.style.setProperty("--safe-area-top", "12px");
    document.documentElement.style.setProperty("--safe-area-bottom", "18px");
  });
  await page.getByRole("button", { name: "Assets", exact: true }).click();
  const operations = page.getByRole("dialog", { name: "Operations", exact: true });
  const tabs = operations.getByRole("tablist", { name: "Operation modes" });
  const tabBox = await tabs.boundingBox();
  const box = await operations.locator(".popup-content").boundingBox();
  expect(box).toMatchObject({ y: 12, height: 290 });
  const body = operations.locator(".popup-body");
  await body.evaluate((element) => {
    element.scrollTop = element.scrollHeight;
  });
  expect(await body.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
  expect(await tabs.boundingBox()).toEqual(tabBox);
  await expect(operations.getByRole("button", { name: "Run Now", exact: true })).toBeInViewport();
  await operations.getByRole("button", { name: "Close popup" }).click();
  await page.getByLabel("Open menu").click();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  const settings = page.getByRole("dialog", { name: "Settings", exact: true });
  expect(await settings.locator(".popup-content").boundingBox()).toMatchObject({
    y: 12,
    height: 290,
  });
  await expect(settings.getByRole("button", { name: "Save", exact: true })).toBeInViewport();
});
