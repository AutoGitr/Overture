import { fireEvent, screen, waitFor } from "@testing-library/svelte";
import { beforeEach, expect, it, vi } from "vitest";
import CollectionGroupsPopup from "../../../lib/popups/CollectionGroupsPopup.svelte";
import { queryClient } from "../../../lib/rest/queryClient";
import { uiState } from "../../../lib/stores/uiState.svelte";
import { mockFetchRoutes } from "../../helpers/fetch";
import { renderWithQueryClient } from "../../helpers/render";
import { navigate } from "../../../lib/router/routes";
import { answerConfirmation } from "../../helpers/notifications";

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

it("exposes rename and delete where an existing group is configured", async () => {
  renderGroups();
  await fireEvent.click(await screen.findByRole("button", { name: "Rename or delete" }));
  expect(screen.getByLabelText("Group name")).toHaveValue("Weekend");
  expect(
    screen.getByRole("option", { name: "Move its collections to Ungrouped" }),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Delete group" })).toBeEnabled();
});

it("does not offer rename or delete for the reserved fallback", async () => {
  uiState.openCollectionGroups("Ungrouped");
  mockFetchRoutes({
    "/api/collections/groups": ["Ungrouped"],
    "/api/library/libraries": [],
    "/api/collections/group-policy": {},
    "/api/collections/defaults": {},
  });
  renderWithQueryClient(CollectionGroupsPopup);
  await screen.findByRole("option", { name: "Ungrouped" });
  expect(screen.queryByRole("button", { name: "Rename or delete" })).not.toBeInTheDocument();
});

it.each(["rename", "delete"])("updates the group picker after %s", async (operation) => {
  const changed = vi.fn();
  uiState.openCollectionGroups("Weekend", changed);
  mockFetchRoutes({
    "/api/collections/groups": ({ init }: { init: RequestInit }) =>
      Response.json(
        init.method === "DELETE"
          ? { collection_ids: [], errors: {} }
          : init.method === "PATCH"
            ? { status: "ok" }
            : ["Weekend"],
      ),
    "/api/library/libraries": [],
    "/api/collections/group-policy": {},
    "/api/collections/defaults": {},
  });
  renderWithQueryClient(CollectionGroupsPopup);
  await fireEvent.click(await screen.findByRole("button", { name: "Rename or delete" }));
  if (operation === "rename") {
    await fireEvent.input(screen.getByLabelText("Group name"), { target: { value: "Evenings" } });
    await fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    await waitFor(() => expect(changed).toHaveBeenCalledWith("Weekend", "Evenings"));
  } else {
    await fireEvent.click(screen.getByRole("button", { name: "Delete group" }));
    await answerConfirmation(true);
    await waitFor(() => expect(changed).toHaveBeenCalledWith("Weekend", ""));
    expect(screen.getByRole("combobox", { name: "Group" })).toHaveValue("__new__");
    expect(screen.getByLabelText("Group name")).toHaveValue("");
  }
});

it("switches between existing and new groups without carrying a pending creation", async () => {
  renderGroups();
  const picker = await screen.findByRole("combobox", { name: "Group" });
  await screen.findByRole("option", { name: "Weekend" });
  await fireEvent.change(picker, { target: { value: "__new__" } });
  await fireEvent.input(screen.getByLabelText("Group name"), { target: { value: "Fresh" } });
  await fireEvent.click(screen.getByRole("button", { name: "Configure" }));
  await fireEvent.change(picker, { target: { value: "Weekend" } });
  await fireEvent.click(await screen.findByRole("button", { name: "Save" }));
  expect(screen.getByRole("combobox", { name: "Group" })).toHaveValue("Weekend");
});
