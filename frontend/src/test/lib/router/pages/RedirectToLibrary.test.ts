import { render } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import RedirectToLibrary from "../../../../lib/router/pages/RedirectToLibrary.svelte";
import { navigate, route } from "../../../../lib/router/routes";

describe("RedirectToLibrary", () => {
  it("replaces an unknown path with the movies library", async () => {
    await navigate("/shows");
    const pushState = vi.spyOn(history, "pushState");

    render(RedirectToLibrary);

    await vi.waitFor(() => expect(route.pathname).toBe("/movies"));
    expect(pushState).not.toHaveBeenCalled();
  });
});
