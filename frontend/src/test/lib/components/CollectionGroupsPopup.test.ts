import { fireEvent, screen, waitFor } from "@testing-library/svelte";
import { beforeEach, expect, it, vi } from "vitest";
import CollectionGroupsPopup from "../../../lib/popups/CollectionGroupsPopup.svelte";
import { queryClient } from "../../../lib/rest/queryClient";
import { uiState } from "../../../lib/stores/uiState.svelte";
import { mockFetchRoutes } from "../../helpers/fetch";
import { answerConfirmation } from "../../helpers/notifications";
import { collection } from "../../helpers/fixtures";
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
  await fireEvent.click(await screen.findByRole("button", { name: "Rename or delete" }));
  await fireEvent.input(screen.getByLabelText("Group name"), { target: { value: "Evenings" } });
  await fireEvent.click(screen.getByRole("button", { name: "Rename" }));
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
    await fireEvent.click(await screen.findByRole("button", { name: "Rename or delete" }));
    await fireEvent.change(screen.getByLabelText("On delete"), {
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

it("offers only an explanation and Take over all for the virtual Unmanaged group", async () => {
  uiState.openCollectionGroups("Unmanaged");
  const { calls } = mockFetchRoutes({
    "/api/collections/groups": ["Weekend", "Unmanaged"],
    "/api/library/libraries": [],
    "/api/collections/bulk-operation": { collection_ids: [3], errors: {}, skipped: {} },
    "/api/collections": [
      collection({ id: 3, managed: false }),
      collection({ id: 4, managed: true }),
    ],
  });
  renderWithQueryClient(CollectionGroupsPopup);

  expect(await screen.findByText(/not a stored group/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Rename or delete" })).not.toBeInTheDocument();
  await fireEvent.click(await screen.findByRole("button", { name: "Take over all (1)" }));
  await waitFor(() =>
    expect(
      JSON.parse(String(calls.find((call) => call.init.method === "POST")?.init.body)),
    ).toEqual({ collection_ids: [3], media_type: "movie", operation: "take_over" }),
  );
});
