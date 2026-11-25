import { fireEvent, screen, waitFor, within } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import CollectionGroupPage from "../../../../lib/router/pages/CollectionGroupPage.svelte";
import { queryClient } from "../../../../lib/rest/queryClient";
import { navigate, route } from "../../../../lib/router/routes";
import { settingsState } from "../../../../lib/stores/settingsState.svelte";
import { uiState } from "../../../../lib/stores/uiState.svelte";
import { syncSelection } from "../../../../lib/stores/syncSelection.svelte";
import { mockFetchRoutes, type FetchCall } from "../../../helpers/fetch";
import {
  appSettings,
  collection,
  collectionCapabilities,
  mediaServers,
} from "../../../helpers/fixtures";
import { answerConfirmation } from "../../../helpers/notifications";
import { chooseOption, renderWithQueryClient } from "../../../helpers/render";

const LIBRARIES = [
  { id: "movies", title: "Movies", media_type: "movie", server_id: 1, count: 3 },
  { id: "shows", title: "Shows", media_type: "show", server_id: 1, count: 2 },
];
const DECADES = {
  dimension: "decade",
  library_ids: ["movies"],
  include: [],
  exclude: [],
  top: null,
  title_format: "{value}s",
  strip_prefix: "",
  strip_suffix: "",
  criteria: { mode: "all", conditions: [], groups: [] },
  smart: false,
  custom_values: [],
  aliases: [],
};

/** The group page's API, the group answering *policy* and taking what is saved. */
function mockGroup(policy: Record<string, unknown> = {}, overrides: Record<string, unknown> = {}) {
  return mockFetchRoutes({
    "/api/library/libraries": LIBRARIES,
    "/api/collections": [
      collection({ id: 12, title: "Saga", collection_group: "Weekend", media_types: ["movie"] }),
    ],
    "/api/collections/groups": [
      { name: "Films", set: null },
      { name: "Weekend", set: null },
    ],
    "/api/collections/defaults": {},
    "/api/collections/capabilities": collectionCapabilities(),
    "/api/collections/groups/Weekend": ({ init }: FetchCall) =>
      Response.json(init.method === "PUT" ? JSON.parse(String(init.body)) : policy),
    ...overrides,
  });
}

function saved(calls: FetchCall[]) {
  const call = calls.find((each) => each.init.method === "PUT");
  return call ? (JSON.parse(String(call.init.body)) as Record<string, unknown>) : null;
}

async function openGroup(name = "Weekend") {
  await navigate("/collections/groups/:groupName", { params: { groupName: name } });
  renderWithQueryClient(CollectionGroupPage);
}

describe("collection group page", () => {
  beforeEach(() => {
    queryClient.clear();
    settingsState.load(
      appSettings({ media_servers: mediaServers("plex"), collections_supported: true }),
    );
  });

  it("lays a group out as a collection is, and lists its collections", async () => {
    mockGroup();
    await openGroup();
    for (const name of ["Group setup", "Group members", "Group settings", "Group schedule"])
      expect(await screen.findByRole("region", { name })).toBeInTheDocument();
    // A plain group has no set to edit.
    expect(screen.queryByRole("region", { name: "Group content" })).toBeNull();
    const members = within(screen.getByRole("list", { name: "Collections in the group" }));
    await fireEvent.click(members.getByRole("button", { name: /Saga/ }));
    await waitFor(() => expect(route.pathname).toBe("/collections/12-saga"));
  });

  it("saves group defaults in Overture alone, leaving the server to the next sync", async () => {
    const { calls } = mockGroup({ minimum_items: 3, sort_title_format: null });
    await openGroup();
    await fireEvent.click(await screen.findByRole("button", { name: "Settings" }));
    await fireEvent.input(await screen.findByLabelText("Minimum members"), {
      target: { value: "2" },
    });
    await chooseOption(screen.getByLabelText("Below minimum"), "Keep on server");
    await fireEvent.input(screen.getByRole("textbox", { name: "Sort title" }), {
      target: { value: "+{title}" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(saved(calls)).not.toBeNull());
    expect(saved(calls)).toMatchObject({
      minimum_items: 2,
      delete_below_minimum: false,
      sort_title_format: "+{title}",
    });
    expect(calls.find((call) => call.init.method === "PUT")?.url).toBe(
      "/api/collections/groups/Weekend?new_set=false",
    );
    expect(
      await screen.findByText('Saved "Weekend". Its collections get it with their next sync.'),
    ).toBeInTheDocument();
    expect(uiState.openPopup).toBeNull();
  });

  it("saves a Plex group's separator, then opens Sync with only the group", async () => {
    const { calls } = mockGroup();
    await openGroup();
    await fireEvent.click(await screen.findByRole("button", { name: "Settings" }));
    await fireEvent.click(await screen.findByRole("checkbox", { name: "Separator" }));
    await fireEvent.click(screen.getByRole("button", { name: "Save and Sync" }));
    await waitFor(() => expect(saved(calls)).toMatchObject({ separator: true }));
    await waitFor(() => expect(uiState.openPopup).toBe("operations"));
    expect(syncSelection.groups).toEqual(["Weekend"]);
    uiState.closePopup();
  });

  it("keeps group edits when the group is fetched again", async () => {
    let served = { sort_title_format: null as string | null };
    const { calls } = mockGroup(
      {},
      { "/api/collections/groups/Weekend": () => Response.json(served) },
    );
    await openGroup();
    await fireEvent.click(await screen.findByRole("button", { name: "Settings" }));
    const sortTitle = await screen.findByRole("textbox", { name: "Sort title" });
    await fireEvent.input(sortTitle, { target: { value: "+{title}" } });
    // A sync elsewhere refreshes the group, with data that differs from what was loaded.
    served = { sort_title_format: "01_{title}" };
    const fetched = calls.length;
    await queryClient.invalidateQueries();
    await waitFor(() =>
      expect(
        calls.slice(fetched).some((call) => call.url === "/api/collections/groups/Weekend"),
      ).toBe(true),
    );
    expect(screen.getByRole("textbox", { name: "Sort title" })).toHaveValue("+{title}");
  });

  it("edits a set's content, and stops it creating collections", async () => {
    const { calls } = mockGroup({ generator: DECADES, minimum_items: 2 });
    await openGroup();
    expect(await screen.findByRole("region", { name: "Group content" })).toBeInTheDocument();
    expect(screen.getByLabelText(/^Title template/)).toHaveValue("{value}s");
    await fireEvent.click(screen.getByRole("button", { name: "Stop creating collections" }));
    expect(screen.queryByRole("region", { name: "Group content" })).toBeNull();
    await fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(saved(calls)).toMatchObject({ generator: null, minimum_items: 2 }));
  });

  it("renames the group and opens it under its new name", async () => {
    const { calls } = mockGroup(
      {},
      {
        "/api/collections/groups/Weekend": ({ init }: FetchCall) =>
          Response.json(init.method === "PATCH" ? { status: "ok" } : {}),
      },
    );
    await openGroup();
    await fireEvent.input(await screen.findByLabelText("Name"), { target: { value: "Evenings" } });
    await fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    await waitFor(() => expect(route.pathname).toBe("/collections/groups/Evenings"));
    const renamed = calls.find((call) => call.init.method === "PATCH");
    expect(JSON.parse(String(renamed?.init.body))).toEqual({ name: "Evenings" });
  });

  it("deletes the group, asking first what happens to its collections", async () => {
    const { calls } = mockGroup(
      {},
      {
        "/api/collections/groups/Weekend": ({ init }: FetchCall) =>
          Response.json(init.method === "DELETE" ? { collection_ids: [12], errors: {} } : {}),
      },
    );
    await openGroup();
    await screen.findByRole("list", { name: "Collections in the group" });
    await fireEvent.click(screen.getByRole("button", { name: "Delete group" }));
    await answerConfirmation(true, "Move them to Films");
    await waitFor(() => expect(route.pathname).toBe("/collections"));
    const deleted = calls.find((call) => call.init.method === "DELETE");
    expect(JSON.parse(String(deleted?.init.body))).toEqual({ collections: "move", group: "Films" });
  });

  it("moves a deleted group's collections to the group chosen", async () => {
    const { calls } = mockGroup(
      {},
      {
        "/api/collections/groups": [
          { name: "Anime", set: null },
          { name: "Weekend", set: null },
        ],
        "/api/collections/groups/Weekend": ({ init }: FetchCall) =>
          Response.json(init.method === "DELETE" ? { collection_ids: [12], errors: {} } : {}),
      },
    );
    await openGroup();
    await screen.findByRole("list", { name: "Collections in the group" });
    await fireEvent.click(screen.getByRole("button", { name: "Delete group" }));
    await answerConfirmation(true, "Move them to Anime");
    await waitFor(() => expect(calls.some((call) => call.init.method === "DELETE")).toBe(true));
    const deleted = calls.find((call) => call.init.method === "DELETE");
    expect(JSON.parse(String(deleted?.init.body))).toEqual({ collections: "move", group: "Anime" });
  });

  it("stays on the group when renaming it is refused, saying why", async () => {
    mockGroup(
      {},
      {
        "/api/collections/groups/Weekend": ({ init }: FetchCall) =>
          init.method === "PATCH"
            ? Response.json({ detail: "A group named Anime already exists" }, { status: 409 })
            : Response.json({}),
      },
    );
    await openGroup();
    await fireEvent.input(await screen.findByLabelText("Name"), { target: { value: "Anime" } });
    await fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    expect(await screen.findByText(/A group named Anime already exists/)).toBeInTheDocument();
    expect(route.pathname).toBe("/collections/groups/Weekend");
  });

  it("exports the group, naming what it left out and offering it to OvertureDB", async () => {
    const createObjectURL = vi.fn(() => "blob:file");
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() }));
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    const { calls } = mockGroup(
      {},
      {
        "/api/collections/presets/export": {
          file: { preset_version: 1, preset: null, groups: [{ name: "Weekend" }], collections: [] },
          refused: [{ title: "Local", reason: "It tests folder, which only this install has" }],
          warnings: [],
          issue: { url: "https://github.com/AutoGitr/OvertureDB/issues/new", notes: [] },
        },
      },
    );
    await openGroup();
    await fireEvent.click(await screen.findByRole("button", { name: "Export group" }));
    expect(
      await screen.findByText("Left out Local: It tests folder, which only this install has"),
    ).toBeInTheDocument();
    expect(createObjectURL).toHaveBeenCalledOnce();
    const exported = calls.find((call) => call.url === "/api/collections/presets/export");
    expect(JSON.parse(String(exported?.init.body))).toEqual({ groups: ["Weekend"] });
    await fireEvent.click(screen.getByRole("button", { name: "Contribute to OvertureDB" }));
    expect(open).toHaveBeenCalledWith(
      "https://github.com/AutoGitr/OvertureDB/issues/new",
      "_blank",
      "noopener",
    );
    open.mockRestore();
    vi.unstubAllGlobals();
  });

  it("says why nothing could be exported, and when exporting fails", async () => {
    let refusing = true;
    mockGroup(
      {},
      {
        "/api/collections/presets/export": () =>
          refusing
            ? Response.json({
                file: null,
                refused: [{ title: "Weekend", reason: "No such group" }],
                warnings: [],
                issue: null,
              })
            : Response.json({ detail: "Export failed" }, { status: 500 }),
      },
    );
    await openGroup();
    await fireEvent.click(await screen.findByRole("button", { name: "Export group" }));
    expect(await screen.findByText("Left out Weekend: No such group")).toBeInTheDocument();
    refusing = false;
    await fireEvent.click(screen.getByRole("button", { name: "Export group" }));
    expect(await screen.findByText(/Export failed/)).toBeInTheDocument();
  });

  it("deletes a group without collections once confirmed, with no choice to make", async () => {
    const { calls } = mockGroup(
      {},
      {
        "/api/collections": [],
        "/api/collections/groups/Weekend": ({ init }: FetchCall) =>
          Response.json(init.method === "DELETE" ? { collection_ids: [], errors: {} } : {}),
      },
    );
    await openGroup();
    await screen.findByText("None yet: choose this group in a collection's Setup.");
    await fireEvent.click(screen.getByRole("button", { name: "Delete group" }));
    await answerConfirmation(true);
    await waitFor(() => expect(route.pathname).toBe("/collections"));
    const deleted = calls.find((call) => call.init.method === "DELETE");
    expect(JSON.parse(String(deleted?.init.body))).toEqual({});
  });
});
