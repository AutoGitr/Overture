import { expect, logIn, test } from "./fixtures";

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
