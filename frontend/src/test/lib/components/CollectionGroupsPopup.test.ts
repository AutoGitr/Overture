import { fireEvent, screen, waitFor } from "@testing-library/svelte";
import { beforeEach, expect, it, vi } from "vitest";
import CollectionGroupsPopup from "../../../lib/popups/CollectionGroupsPopup.svelte";
import { queryClient } from "../../../lib/rest/queryClient";
import { uiState } from "../../../lib/stores/uiState.svelte";
import { mockFetchRoutes } from "../../helpers/fetch";
import { renderWithQueryClient } from "../../helpers/render";
import { navigate } from "../../../lib/router/routes";

beforeEach(async () => {
  queryClient.clear();
  await navigate("/movies/collections");
  uiState.openCollectionGroups("Weekend");
});

function renderGroups() {
  const result = mockFetchRoutes({
    "/api/collections/groups": ["Weekend"],
    "/api/library/libraries": [],
    "/api/collections/group-policy": {},
    "/api/collections/defaults": {},
  });
  renderWithQueryClient(CollectionGroupsPopup);
  return result;
}

it("reports a new group once it is saved, so the collection can take it", async () => {
  const changed = vi.fn();
  uiState.openCollectionGroups("", changed);
  renderGroups();
  await fireEvent.input(await screen.findByLabelText("Group name"), {
    target: { value: "Fresh" },
  });
  await fireEvent.click(screen.getByRole("button", { name: "Configure" }));
  await fireEvent.click(await screen.findByRole("button", { name: "Save" }));
  await waitFor(() => expect(changed).toHaveBeenCalledWith("", "Fresh"));
  expect(uiState.openPopup).toBeNull();
});

it("stays open after creating a group when opened from the sidebar", async () => {
  uiState.openCollectionGroups();
  renderGroups();
  await fireEvent.input(await screen.findByLabelText("Group name"), {
    target: { value: "Fresh" },
  });
  await fireEvent.click(screen.getByRole("button", { name: "Configure" }));
  await fireEvent.click(await screen.findByRole("button", { name: "Save" }));
  await waitFor(() => expect(uiState.openPopup).toBe("collection-groups"));
});
