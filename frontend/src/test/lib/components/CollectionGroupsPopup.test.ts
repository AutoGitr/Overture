import { fireEvent, screen, waitFor } from "@testing-library/svelte";
import { beforeEach, expect, it, vi } from "vitest";
import CollectionGroupsPopup from "../../../lib/popups/CollectionGroupsPopup.svelte";
import { queryClient } from "../../../lib/rest/queryClient";
import { uiState } from "../../../lib/stores/uiState.svelte";
import { mockFetchRoutes } from "../../helpers/fetch";
import { answerConfirmation } from "../../helpers/notifications";
import { renderWithQueryClient } from "../../helpers/render";
import { navigate } from "../../../lib/router/routes";

beforeEach(async () => {
  queryClient.clear();
  await navigate("/movies/collections");
  uiState.openCollectionGroups("Weekend");
});

function renderGroups() {
  const result = mockFetchRoutes({
    "/api/collections/groups": ({ init }: { init: RequestInit }) =>
      Response.json(
        init.method === "DELETE"
          ? { collection_ids: [12], errors: {} }
          : init.method === "PATCH"
            ? { status: "ok" }
            : ["Weekend"],
      ),
    "/api/library/libraries": [],
    "/api/collections/group-policy": {},
    "/api/collections/defaults": {},
  });
  renderWithQueryClient(CollectionGroupsPopup);
  return result;
}

it("renames the selected group", async () => {
  const changed = vi.fn();
  uiState.openCollectionGroups("Weekend", changed);
  const { calls } = renderGroups();
  await fireEvent.click(await screen.findByRole("button", { name: "Manage group" }));
  await fireEvent.input(screen.getByLabelText("Group name"), { target: { value: "Evenings" } });
  await fireEvent.click(screen.getByRole("button", { name: "Rename group" }));
  await waitFor(() =>
    expect(calls.find((call) => call.init.method === "PATCH")?.init.body).toBe(
      JSON.stringify({ name: "Evenings" }),
    ),
  );
  await waitFor(() => expect(changed).toHaveBeenCalledWith("Weekend", "Evenings"));
});

it.each(["keep", "overture", "server", "both"])(
  "confirms and submits the %s deletion scope",
  async (scope) => {
    const { calls } = renderGroups();
    await fireEvent.click(await screen.findByRole("button", { name: "Manage group" }));
    await fireEvent.change(screen.getByLabelText("When deleting this group"), {
      target: { value: scope },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Delete group" }));
    await answerConfirmation(true);
    await waitFor(() =>
      expect(calls.find((call) => call.init.method === "DELETE")?.init.body).toBe(
        JSON.stringify({ collections: scope }),
      ),
    );
  },
);
