import { screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import LibraryPage from "../../../../lib/router/pages/LibraryPage.svelte";
import { navigate } from "../../../../lib/router/routes";
import { uiState } from "../../../../lib/stores/uiState.svelte";
import { renderWithQueryClient } from "../../../helpers/render";

describe("LibraryPage", () => {
  it("shows the library with nothing selected", async () => {
    uiState.mobileShowDetail = true;
    await navigate("/movies");

    renderWithQueryClient(LibraryPage);

    expect(screen.getByText("Select a movie from the sidebar")).toBeInTheDocument();
    expect(uiState.mobileShowDetail).toBe(false);
  });
});
