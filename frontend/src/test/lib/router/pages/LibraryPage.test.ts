import { waitFor } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import LibraryPage from "../../../../lib/router/pages/LibraryPage.svelte";
import { navigate } from "../../../../lib/router/routes";
import { collectionState } from "../../../../lib/stores/collectionState.svelte";
import { selectedState } from "../../../../lib/stores/selectedState.svelte";
import { uiState } from "../../../../lib/stores/uiState.svelte";
import { collection, mediaItem } from "../../../helpers/fixtures";
import { renderWithQueryClient } from "../../../helpers/render";

describe("LibraryPage", () => {
  it("drops whatever an earlier route had selected and shows the library", async () => {
    selectedState.selectItem(mediaItem({ id: 4 }));
    collectionState.selectCollection(collection({ id: "12" }));
    uiState.mobileShowDetail = true;
    await navigate("/movies");

    renderWithQueryClient(LibraryPage);

    await waitFor(() => expect(selectedState.subject).toBeNull());
    expect(collectionState.selectedCollection).toBeNull();
    expect(uiState.mobileShowDetail).toBe(false);
  });
});
