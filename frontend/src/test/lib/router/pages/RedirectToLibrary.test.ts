import { fireEvent } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import RedirectToLibrary from "../../../../lib/router/pages/RedirectToLibrary.svelte";
import { navigate, route } from "../../../../lib/router/routes";
import { queryClient } from "../../../../lib/rest/queryClient";
import { mockFetch, mockFetchRoutes, type FetchCall } from "../../../helpers/fetch";
import { renderWithQueryClient } from "../../../helpers/render";

describe("RedirectToLibrary", () => {
  beforeEach(async () => {
    queryClient.clear();
    await navigate("/movies/collections");
  });

  it.each([
    { movies: true, shows: true, expected: "/movies" },
    { movies: true, shows: false, expected: "/movies" },
    { movies: false, shows: true, expected: "/shows" },
    { movies: false, shows: false, expected: "/movies" },
  ])(
    "selects $expected with movies=$movies and shows=$shows",
    async ({ movies, shows, expected }) => {
      mockFetchRoutes({
        "/api/library/libraries": ({ url }: FetchCall) =>
          Response.json(
            (url.includes("media_type=movie") ? movies : shows)
              ? [{ id: "1", title: "Library", count: 1 }]
              : [],
          ),
      });
      const pushState = vi.spyOn(history, "pushState");

      renderWithQueryClient(RedirectToLibrary);

      await vi.waitFor(() => expect(route.pathname).toBe(expected));
      expect(pushState).not.toHaveBeenCalled();
    },
  );

  it("keeps the route on failure and offers a retry", async () => {
    mockFetch({ detail: "Unavailable" }, { status: 400 });
    const view = renderWithQueryClient(RedirectToLibrary);
    await view.findByRole("alert");
    expect(route.pathname).toBe("/movies/collections");
    mockFetch([]);
    await fireEvent.click(view.getByRole("button", { name: "Retry libraries" }));
    await vi.waitFor(() => expect(route.pathname).toBe("/movies"));
  });
});
