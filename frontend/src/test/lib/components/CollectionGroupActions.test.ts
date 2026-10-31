import { fireEvent, screen, waitFor } from "@testing-library/svelte";
import { beforeEach, expect, it, vi } from "vitest";
import CollectionGroupActions from "../../../lib/components/CollectionGroupActions.svelte";
import { queryClient } from "../../../lib/rest/queryClient";
import { mockFetchRoutes } from "../../helpers/fetch";
import { answerConfirmation } from "../../helpers/notifications";
import { renderWithQueryClient } from "../../helpers/render";
import { appSettings } from "../../helpers/fixtures";
import { settingsState } from "../../../lib/stores/settingsState.svelte";

beforeEach(() => {
  queryClient.clear();
  settingsState.load(appSettings());
});

function renderActions(props: { onrename?: () => void; ondelete?: () => void } = {}) {
  const result = mockFetchRoutes({
    "/api/collections/groups": ({ init }: { init: RequestInit }) =>
      Response.json(
        init.method === "DELETE"
          ? { collection_ids: [12], errors: {} }
          : init.method === "PATCH"
            ? { status: "ok" }
            : ["Weekend", "Evenings"],
      ),
  });
  renderWithQueryClient(CollectionGroupActions, {
    group: "Weekend",
    mediaType: "movie",
    onrename: props.onrename ?? vi.fn(),
    ondelete: props.ondelete ?? vi.fn(),
  });
  return result;
}

it("renames the group", async () => {
  const onrename = vi.fn();
  const { calls } = renderActions({ onrename });
  await fireEvent.click(await screen.findByRole("button", { name: "Rename or delete" }));
  await fireEvent.input(screen.getByLabelText("Group name"), { target: { value: "Evenings" } });
  await fireEvent.click(screen.getByRole("button", { name: "Rename" }));
  await waitFor(() =>
    expect(calls.find((call) => call.init.method === "PATCH")?.init.body).toBe(
      JSON.stringify({ name: "Evenings" }),
    ),
  );
  await waitFor(() => expect(onrename).toHaveBeenCalledWith("Evenings"));
});

it.each(["keep", "overture", "both"])(
  "confirms and submits the %s deletion scope",
  async (scope) => {
    const { calls } = renderActions();
    await fireEvent.click(await screen.findByRole("button", { name: "Rename or delete" }));
    await fireEvent.change(screen.getByLabelText("On delete"), {
      target: { value: scope },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Delete group" }));
    await answerConfirmation(true);
    await waitFor(() =>
      expect(calls.find((call) => call.init.method === "DELETE")?.init.body).toBe(
        JSON.stringify({ collections: scope, group: null }),
      ),
    );
  },
);

it("moves the collections to the chosen group, which it needs first", async () => {
  const { calls } = renderActions();
  await fireEvent.click(await screen.findByRole("button", { name: "Rename or delete" }));
  await fireEvent.change(screen.getByLabelText("On delete"), { target: { value: "move" } });
  const remove = screen.getByRole("button", { name: "Delete group" });
  expect(remove).toBeDisabled();
  await screen.findByRole("option", { name: "Evenings" });
  await fireEvent.change(screen.getByLabelText("Move to"), { target: { value: "Evenings" } });
  await fireEvent.click(remove);
  await answerConfirmation(true);
  await waitFor(() =>
    expect(calls.find((call) => call.init.method === "DELETE")?.init.body).toBe(
      JSON.stringify({ collections: "move", group: "Evenings" }),
    ),
  );
});

it("keeps the group when deletion is cancelled", async () => {
  const ondelete = vi.fn();
  const { calls } = renderActions({ ondelete });
  await fireEvent.click(screen.getByRole("button", { name: "Rename or delete" }));
  await fireEvent.click(screen.getByRole("button", { name: "Delete group" }));
  await answerConfirmation(false);
  expect(calls.some((call) => call.init.method === "DELETE")).toBe(false);
  expect(ondelete).not.toHaveBeenCalled();
});

it.each(["rename", "delete", "partial deletion"])(
  "keeps the selected group after failed %s",
  async (operation) => {
    const onrename = vi.fn();
    const ondelete = vi.fn();
    mockFetchRoutes({
      "/api/collections/groups": ({ init }: { init: RequestInit }) => {
        if (init.method === "GET") return Response.json(["Weekend"]);
        return operation === "partial deletion"
          ? Response.json({ collection_ids: [], errors: { 12: "Server unavailable" } })
          : Response.json({ detail: "Server unavailable" }, { status: 422 });
      },
    });
    renderWithQueryClient(CollectionGroupActions, {
      group: "Weekend",
      mediaType: "movie",
      onrename,
      ondelete,
    });
    await fireEvent.click(screen.getByRole("button", { name: "Rename or delete" }));
    if (operation === "rename") {
      await fireEvent.input(screen.getByLabelText("Group name"), { target: { value: "New name" } });
      await fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    } else {
      await fireEvent.click(screen.getByRole("button", { name: "Delete group" }));
      await answerConfirmation(true);
    }
    expect(await screen.findByText(/Server unavailable/)).toBeInTheDocument();
    expect(onrename).not.toHaveBeenCalled();
    expect(ondelete).not.toHaveBeenCalled();
  },
);
