import { mediaItem, season } from "../helpers/fixtures";
import { expect, logIn, test } from "./fixtures";

test("a show's seasons open, step through and close without an error", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const show = mediaItem({ id: 2, title: "Twin Peaks", media_type: "show", year: 1990 });
  await page.route("**/api/library/items/2", (route) => route.fulfill({ json: show }));
  await page.route("**/api/library/items/2/seasons", (route) =>
    route.fulfill({
      json: [1, 2].map((num) =>
        season({ id: 10 + num, media_item_id: 2, season_num: num, title: `Season ${num}` }),
      ),
    }),
  );
  await logIn(page, "/shows/2-twin-peaks/art/seasons");
  const main = page.getByRole("main");
  const paste = (label: string) =>
    page.getByRole("button", { name: `Paste URL & save as ${label}` });

  await main.getByRole("button", { name: /^Season 1/ }).click();
  await expect(paste("season poster")).toBeVisible();
  await main.getByRole("button", { name: "Next" }).click();
  await expect(main.getByText("Season 2", { exact: true })).toBeVisible();
  // Back to the grid: the header offers nothing to paste into.
  await main.getByRole("button", { name: "Twin Peaks" }).click();
  await expect(main.getByRole("button", { name: /^Season 1/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /Paste URL/ })).toHaveCount(0);
  await page.getByRole("tab", { name: "Poster" }).click();
  await expect(paste("poster")).toBeVisible();

  expect(errors).toEqual([]);
});
