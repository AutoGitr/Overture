import { fireEvent, screen, waitFor, within } from "@testing-library/svelte";
import { beforeEach, describe, expect, it } from "vitest";
import GroupSettingsHarness from "../../helpers/GroupSettingsHarness.svelte";
import CollectionPage from "../../../lib/router/pages/CollectionPage.svelte";
import { queryClient } from "../../../lib/rest/queryClient";
import {
  goToCollectionView,
  navigate,
  route,
  routedCollectionArtType,
  routedCollectionId,
  routedCollectionView,
} from "../../../lib/router/routes";
import { settingsState } from "../../../lib/stores/settingsState.svelte";
import { uiState } from "../../../lib/stores/uiState.svelte";
import { mockFetchRoutes } from "../../helpers/fetch";
import {
  appSettings,
  collectionCapabilities,
  collectionDetail,
  collectionRule,
  mediaItem,
} from "../../helpers/fixtures";
import { answerConfirmation } from "../../helpers/notifications";
import { renderWithQueryClient } from "../../helpers/render";

const members = [
  mediaItem({ id: 1, title: "First", library_id: "movies", server_item_id: "m1" }),
  mediaItem({ id: 2, title: "Second", library_id: "movies", server_item_id: "m2" }),
];
const third = mediaItem({ id: 3, title: "Third", library_id: "other", server_item_id: "m3" });
// Append keeps members chosen by hand as well as what the criteria match.
const rule = collectionRule({ sync_mode: "append" });
const detail = collectionDetail({
  id: 12,
  title: "Saga",
  library_id: "movies",
  members,
  child_count: 2,
  rule,
  effective_sync_mode: "append",
});
const capabilities = collectionCapabilities();

/** Add a source condition to the criteria and fill in its one input. */
async function addSource(source: string, input: string, value: string) {
  await fireEvent.click(await screen.findByRole("button", { name: "Condition" }));
  await fireEvent.change(screen.getByLabelText("Criteria condition 1 field"), {
    target: { value: `source:${source}` },
  });
  await fireEvent.change(screen.getByLabelText(input), { target: { value } });
}

function addTmdbTitles(ids: string) {
  return addSource("tmdb_item", "Criteria condition 1 TMDB IDs", ids);
}

/** Choose exactly one library in Setup's Libraries. */
async function onlyLibrary(scope: Pick<typeof screen, "getByRole">, name: string) {
  const libraries = within(scope.getByRole("group", { name: "Libraries" }));
  const chosen = libraries.getByRole("checkbox", { name });
  for (const box of libraries.getAllByRole<HTMLInputElement>("checkbox"))
    if (box.checked !== (box === chosen)) await fireEvent.click(box);
}

describe("collection management", () => {
  beforeEach(async () => {
    queryClient.clear();
    settingsState.load(appSettings({ media_server: "plex", collections_supported: true }));
    await navigate("/movies/collections/:collectionSlug", {
      params: { collectionSlug: "12-saga" },
    });
  });

  it("identifies a retained collection that is absent from the media server", async () => {
    mockFetchRoutes({
      "/api/collections/defaults": {},
      "/api/collections/capabilities": capabilities,
      "/api/collections/12/rule": rule,
      "/api/collections/groups": [],
      "/api/collections/12": { ...detail, withheld: true },
    });
    renderWithQueryClient(CollectionPage);
    expect(await screen.findByText("Not on server")).toHaveAttribute(
      "title",
      "Saved in Overture only",
    );
  });

  it("removes members through the API and keeps the collection view in sync", async () => {
    const { calls } = mockFetchRoutes({
      "/api/collections/defaults": {},
      "/api/collections/capabilities": capabilities,
      "/api/collections/12/rule": rule,
      "/api/collections/groups": [],
      "/api/collections/12": detail,
      "/api/library/items": { items: members, total: 2 },
      "/api/collections/12/members": { ...detail, members: [members[1]], child_count: 1 },
    });
    renderWithQueryClient(CollectionPage);
    await fireEvent.click(await screen.findByRole("button", { name: "Members" }));
    await fireEvent.click(
      await screen.findByRole("button", { name: "Remove First from collection" }),
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "Remove First from collection" }),
      ).not.toBeInTheDocument(),
    );
    const put = calls.find((call) => call.init.method === "PUT");
    // Member edits stay in Overture until the collection is synced.
    expect(put?.url).toContain("to_server=false");
    expect(put?.init.body).toBe(JSON.stringify({ member_ids: [2], order_type: "release.asc" }));
  });

  it("saves settings without losing nullable inheritance", async () => {
    let saved = false;
    mockFetchRoutes({
      "/api/collections/defaults": {},
      "/api/collections/capabilities": capabilities,
      "/api/collections/12/rule": rule,
      "/api/collections/groups": [],
      "/api/collections/12": ({ init }: { init: RequestInit }) => {
        if (init.method === "PUT") {
          saved = true;
          return Response.json({ ...detail, title: "New saga" });
        }
        return Response.json(detail);
      },
    });
    goToCollectionView(detail, "configure");
    renderWithQueryClient(CollectionPage);
    await fireEvent.input(await screen.findByLabelText("Title"), { target: { value: "New saga" } });
    await fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(saved).toBe(true));
    expect(await screen.findByRole("heading", { name: "New saga" })).toBeInTheDocument();
  });

  it("saves rule overrides and runs a saved rule", async () => {
    const { calls } = mockFetchRoutes({
      "/api/collections/defaults": {},
      "/api/collections/capabilities": capabilities,
      "/api/collections/groups": [],
      "/api/collections/12": { ...detail, rule },
      "/api/collections/12/rule": rule,
      "/api/collections/12/sync": { added: 1, removed: 0, skipped: false, deleted: false },
    });
    goToCollectionView(detail, "configure");
    renderWithQueryClient(CollectionPage);
    await fireEvent.change(await screen.findByLabelText("Sync mode"), {
      target: { value: "append" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls.some((call) => call.init.method === "PUT" && !call.url.includes("/rule"))).toBe(
        true,
      ),
    );
    await waitFor(() =>
      expect(calls.some((call) => call.url.includes("/rule") && call.init.method === "PUT")).toBe(
        true,
      ),
    );
    const body = JSON.parse(
      String(
        calls.find((call) => call.url.includes("/rule") && call.init.method === "PUT")?.init.body,
      ),
    );
    expect(body.sync_mode).toBe("append");
    expect(body.minimum_items).toBeNull();
    expect(calls.some((call) => call.url.includes("/sync") && call.init.method === "POST")).toBe(
      false,
    );
    await fireEvent.click(screen.getByRole("button", { name: "Save and Sync" }));
    await waitFor(() =>
      expect(calls.some((call) => call.url.includes("/sync") && call.init.method === "POST")).toBe(
        true,
      ),
    );
  });

  it("saves an existing or custom group with the complete Configure draft", async () => {
    const { calls } = mockFetchRoutes({
      "/api/collections/defaults": {},
      "/api/collections/capabilities": capabilities,
      "/api/collections/12/rule": rule,
      "/api/collections/groups": ["default-decades", "Weekend"],
      "/api/collections/12": ({ init }: { init: RequestInit }) =>
        Response.json(init.method === "PUT" ? { ...detail, collection_group: "Weekend" } : detail),
    });
    renderWithQueryClient(CollectionPage);
    const group = await screen.findByLabelText("Group");
    await screen.findByRole("option", { name: "Weekend" });
    await fireEvent.change(group, { target: { value: "Weekend" } });
    await fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls.some((call) => call.init.method === "PUT" && !call.url.includes("/rule"))).toBe(
        true,
      ),
    );
    expect(
      JSON.parse(
        String(
          calls.find((call) => call.init.method === "PUT" && !call.url.includes("/rule"))?.init
            .body,
        ),
      ),
    ).toMatchObject({ collection_group: "Weekend" });
  });

  it("creates a group only through the groups popup, then assigns it", async () => {
    mockFetchRoutes({
      "/api/collections/defaults": {},
      "/api/collections/capabilities": capabilities,
      "/api/collections/12/rule": rule,
      "/api/collections/groups": ["Weekend"],
      "/api/collections/12": detail,
    });
    renderWithQueryClient(CollectionPage);
    const group = await screen.findByLabelText("Group");
    await screen.findByRole("option", { name: "Weekend" });
    expect(screen.queryByRole("button", { name: "Manage groups" })).toBeNull();
    await fireEvent.change(group, { target: { value: "__new__" } });
    expect(uiState.openPopup).toBe("collection-groups");
    expect(group).toHaveValue("Ungrouped");
    uiState.collectionGroupChanged("", "Fresh");
    await waitFor(() => expect(group).toHaveValue("Fresh"));
    uiState.closePopup();
  });

  it("only offers manual additions for manual and append collections", async () => {
    mockFetchRoutes({
      "/api/collections/defaults": {},
      "/api/collections/capabilities": capabilities,
      "/api/collections/12/rule": rule,
      "/api/collections/12": { ...detail, rule: { ...rule, sync_mode: "sync" } },
    });
    renderWithQueryClient(CollectionPage);
    await screen.findByRole("heading", { name: "Saga" });
    expect(screen.queryByLabelText("Add item")).toBeNull();
    const settings = within(await screen.findByRole("region", { name: "Collection settings" }));
    expect(settings.getByLabelText("Sort")).toBeInTheDocument();
  });

  it("supports keyboard mode navigation while keeping both header boxes", async () => {
    mockFetchRoutes({
      "/api/collections/defaults": {},
      "/api/collections/capabilities": capabilities,
      "/api/collections/12/rule": rule,
      "/api/collections/groups": [],
      "/api/collections/12": detail,
      "/api/collections/12/art/poster/sources": { sources: {}, current_url: null },
    });
    const { container } = renderWithQueryClient(CollectionPage);
    const configure = await screen.findByRole("tab", { name: "Configure" });
    await fireEvent.keyDown(configure, { key: "ArrowRight" });
    expect(await screen.findByRole("tab", { name: "Art", selected: true })).toHaveFocus();
    const boxes = container.querySelectorAll(".detail-sections > .tab-bar");
    expect(boxes).toHaveLength(2);
    expect(boxes[0]?.contains(screen.getByRole("group", { name: "Record actions" }))).toBe(true);
    expect(boxes[1]?.contains(screen.getByRole("tablist", { name: "Art categories" }))).toBe(true);
  });

  it("defaults a fresh draft to its only library and leaves multiple libraries unselected", async () => {
    mockFetchRoutes({
      "/api/collections/defaults": {},
      "/api/collections/capabilities": capabilities,
      "/api/collections/12/rule": rule,
      "/api/library/libraries": [{ id: "movies", title: "Movies", count: 2 }],
      "/api/library/items": { items: members, total: 2 },
      "/api/collections/groups": [],
    });
    await navigate("/movies/collections/new");
    const view = renderWithQueryClient(CollectionPage);
    await waitFor(() => expect(screen.getByRole("checkbox", { name: "Movies" })).toBeChecked());
    expect(screen.getByLabelText("Title")).toHaveValue("");
    view.unmount();
    queryClient.clear();
    mockFetchRoutes({
      "/api/collections/defaults": {},
      "/api/collections/capabilities": capabilities,
      "/api/collections/12/rule": rule,
      "/api/library/libraries": [
        { id: "movies", title: "Movies", count: 2 },
        { id: "other", title: "Other", count: 1 },
      ],
      "/api/collections/groups": [],
    });
    await navigate("/movies/collections/new");
    renderWithQueryClient(CollectionPage);
    await screen.findByRole("checkbox", { name: "Other" });
    for (const name of ["Movies", "Other"])
      expect(screen.getByRole("checkbox", { name })).not.toBeChecked();
  });

  it("edits an explicit TMDB ID without matching or automatic voting controls", async () => {
    const { calls } = mockFetchRoutes({
      "/api/collections/defaults": {},
      "/api/collections/capabilities": capabilities,
      "/api/collections/12/rule": rule,
      "/api/collections/12": { ...detail, tmdb_collection_id: 10 },
      "/api/collections/groups": [],
    });
    renderWithQueryClient(CollectionPage);
    const input = await screen.findByLabelText("TMDB collection ID");
    expect(input).toHaveValue(10);
    expect(screen.queryByRole("button", { name: "Reset to auto" })).toBeNull();
    await fireEvent.input(input, { target: { value: "99" } });
    await fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls.some((call) => call.init.method === "PUT" && !call.url.includes("/rule"))).toBe(
        true,
      ),
    );
    expect(
      JSON.parse(
        String(
          calls.find((call) => call.init.method === "PUT" && !call.url.includes("/rule"))?.init
            .body,
        ),
      ),
    ).toMatchObject({ tmdb_collection_id: 99 });
  });

  it("shows collection artwork status, clears a selected slot, and skips candidates without an ID", async () => {
    const selected = {
      ...detail,
      poster_url: "https://example.test/poster.jpg",
      poster_status: "complete",
      art_status: "partial",
    };
    const { calls } = mockFetchRoutes({
      "/api/collections/defaults": {},
      "/api/collections/capabilities": capabilities,
      "/api/collections/12/rule": rule,
      "/api/collections/12": selected,
      "/api/collections/12/art/poster": {
        poster_url: null,
        background_url: null,
        poster_status: "partial",
        background_status: "missing",
        art_status: "partial",
      },
    });
    goToCollectionView(detail, "art");
    renderWithQueryClient(CollectionPage);
    const clear = await screen.findByRole("button", { name: "Clear poster" });
    expect(clear.querySelector("[data-status]")).toHaveAttribute("data-status", "success");
    await fireEvent.click(clear);
    await answerConfirmation(true);
    await waitFor(() => expect(calls.some((call) => call.init.method === "DELETE")).toBe(true));
    expect(calls.some((call) => call.url.includes("/sources"))).toBe(false);
    expect(await screen.findByText(/Set a TMDB collection ID to browse/)).toBeVisible();
  });

  it("creates a collection from explicit TMDB IDs", async () => {
    const { calls } = mockFetchRoutes({
      "/api/collections/defaults": {},
      "/api/collections/capabilities": capabilities,
      "/api/collections/12/rule": rule,
      "/api/collections/groups": [],
      "/api/library/libraries": [{ id: "movies", title: "Movies", count: 2 }],
      "/api/library/items": { items: members, total: 2 },
      "/api/collections": detail,
    });
    await navigate("/movies/collections/new");
    renderWithQueryClient(CollectionPage);
    await fireEvent.input(screen.getByLabelText("Title"), { target: { value: "Saga" } });
    await screen.findByRole("checkbox", { name: "Movies" });
    await onlyLibrary(screen, "Movies");
    await addTmdbTitles("11");
    await fireEvent.click(screen.getByRole("button", { name: "Save and Create" }));
    await waitFor(() => expect(route.pathname).toBe("/movies/collections/12-saga"));
    expect(
      JSON.parse(String(calls.find((call) => call.init.method === "POST")?.init.body)),
    ).toMatchObject({
      title: "Saga",
      library_id: "movies",
      rule: {
        criteria: {
          mode: "all",
          conditions: [
            { kind: "source", operator: "is", source: { type: "tmdb_item", tmdb_ids: [11] } },
          ],
        },
      },
    });
  });

  it.each([
    { button: "Move First down", expected: [2, 1] },
    { button: "Move Second up", expected: [2, 1] },
  ])("reorders members using $button", async ({ button, expected }) => {
    const { calls } = mockFetchRoutes({
      "/api/collections/defaults": {},
      "/api/collections/capabilities": capabilities,
      "/api/collections/12/rule": rule,
      "/api/collections/groups": [],
      "/api/collections/12": detail,
      "/api/library/items": { items: members, total: members.length },
      "/api/collections/12/members": {
        ...detail,
        order_type: "custom",
        members: [members[1], members[0]],
      },
    });
    renderWithQueryClient(CollectionPage);
    await fireEvent.click(await screen.findByRole("button", { name: "Members" }));
    expect(await screen.findByRole("button", { name: "Move First up" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Move Second down" })).toBeDisabled();
    await fireEvent.click(screen.getByRole("button", { name: button }));
    await waitFor(() =>
      expect(calls.some((call) => call.init.method === "PUT" && !call.url.includes("/rule"))).toBe(
        true,
      ),
    );
    expect(JSON.parse(String(calls.find((call) => call.init.method === "PUT")?.init.body))).toEqual(
      { member_ids: expected, order_type: "custom" },
    );
    await waitFor(() => expect(screen.getAllByRole("listitem")[0]).toHaveTextContent("Second"));
  });

  it("drops a member anywhere on another row at that row's position", async () => {
    const all = [...members, third];
    const { calls } = mockFetchRoutes({
      "/api/collections/defaults": {},
      "/api/collections/capabilities": capabilities,
      "/api/collections/12/rule": rule,
      "/api/collections/groups": [],
      "/api/collections/12": { ...detail, members: all },
      "/api/library/items": { items: all, total: all.length },
      "/api/collections/12/members": {
        ...detail,
        order_type: "custom",
        members: [members[1], third, members[0]],
      },
    });
    renderWithQueryClient(CollectionPage);
    await fireEvent.click(await screen.findByRole("button", { name: "Members" }));
    await fireEvent.dragStart(await screen.findByRole("button", { name: "Drag First to reorder" }));
    const target = screen
      .getAllByRole("listitem")
      .find((row) => within(row).queryByRole("button", { name: "Remove Third from collection" }));
    if (!target) throw new Error("Third collection member is missing");
    await fireEvent.drop(target);
    await waitFor(() =>
      expect(calls.some((call) => call.init.method === "PUT" && !call.url.includes("/rule"))).toBe(
        true,
      ),
    );
    expect(JSON.parse(String(calls.find((call) => call.init.method === "PUT")?.init.body))).toEqual(
      { member_ids: [2, 3, 1], order_type: "custom" },
    );
  });

  it("keeps member search trimmed and excludes collection members", async () => {
    mockFetchRoutes({
      "/api/collections/defaults": {},
      "/api/collections/capabilities": capabilities,
      "/api/collections/12/rule": rule,
      "/api/collections/groups": [],
      "/api/collections/12": { ...detail, members: [members[0]] },
      "/api/library/items": { items: members, total: 2 },
    });
    renderWithQueryClient(CollectionPage);
    await fireEvent.click(await screen.findByRole("button", { name: "Members" }));
    const search = await screen.findByLabelText("Add item");
    await fireEvent.input(search, { target: { value: "   " } });
    expect(screen.queryByText("No matching library items.")).not.toBeInTheDocument();
    await fireEvent.input(search, { target: { value: "  SECOND  " } });
    expect(await screen.findByRole("button", { name: "Add Second" })).toBeInTheDocument();
    await fireEvent.input(search, { target: { value: " First " } });
    expect(screen.queryByRole("button", { name: "Add First" })).not.toBeInTheDocument();
  });

  it("keeps explicit sources when switching libraries and trims the submitted title", async () => {
    const { calls } = mockFetchRoutes({
      "/api/collections/defaults": {},
      "/api/collections/capabilities": capabilities,
      "/api/collections/12/rule": rule,
      "/api/collections/groups": [],
      "/api/library/libraries": [
        { id: "movies", title: "Movies", count: 2 },
        { id: "other", title: "Other", count: 1 },
      ],
      "/api/library/items": { items: [...members, third], total: 3 },
      "/api/collections": detail,
    });
    await navigate("/movies/collections/new");
    renderWithQueryClient(CollectionPage);
    expect(screen.queryByLabelText("Search members")).toBeNull();
    await screen.findByRole("checkbox", { name: "Movies" });
    await onlyLibrary(screen, "Movies");
    await addTmdbTitles("11");
    const submit = screen.getByRole("button", { name: "Save and Create" });
    expect(submit).toBeDisabled();
    await fireEvent.input(screen.getByLabelText("Title"), { target: { value: "  Saga  " } });
    expect(submit).toBeEnabled();
    await onlyLibrary(screen, "Other");
    expect(screen.getByRole("button", { name: "Save and Create" })).toBeEnabled();
    expect(screen.getByLabelText("Criteria condition 1 TMDB IDs")).toHaveValue("11");
    await fireEvent.click(screen.getByRole("button", { name: "Save and Create" }));
    await waitFor(() => expect(calls.some((call) => call.init.method === "POST")).toBe(true));
    expect(
      JSON.parse(String(calls.find((call) => call.init.method === "POST")?.init.body)),
    ).toMatchObject({
      title: "Saga",
      library_id: "other",
      rule: {
        criteria: {
          mode: "all",
          conditions: [
            { kind: "source", operator: "is", source: { type: "tmdb_item", tmdb_ids: [11] } },
          ],
        },
      },
    });
  });

  it("retries a refused collection creation from its error message", async () => {
    let attempts = 0;
    mockFetchRoutes({
      "/api/collections/defaults": {},
      "/api/collections/capabilities": capabilities,
      "/api/collections/12/rule": rule,
      "/api/collections/groups": [],
      "/api/library/libraries": [{ id: "movies", title: "Movies", count: 2 }],
      "/api/library/items": { items: members, total: 2 },
      "/api/collections": () =>
        ++attempts === 1
          ? Response.json({ detail: "Create refused" }, { status: 422 })
          : Response.json(detail),
    });
    await navigate("/movies/collections/new");
    renderWithQueryClient(CollectionPage);
    await fireEvent.input(screen.getByLabelText("Title"), { target: { value: "Saga" } });
    await screen.findByRole("checkbox", { name: "Movies" });
    await onlyLibrary(screen, "Movies");
    await addTmdbTitles("11");
    await fireEvent.click(screen.getByRole("button", { name: "Save and Create" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Create refused");
    await fireEvent.click(await screen.findByRole("button", { name: "Retry collection creation" }));
    await waitFor(() => expect(attempts).toBe(2));
    await waitFor(() => expect(route.pathname).toBe("/movies/collections/12-saga"));
  });

  it("shows a saved rule immediately without needing a live event", async () => {
    mockFetchRoutes({
      "/api/collections/defaults": {},
      "/api/collections/capabilities": capabilities,
      "/api/collections/groups": [],
      "/api/library/libraries": [{ id: "movies", title: "Movies", count: 2 }],
      "/api/library/items": { items: members, total: 2 },
      "/api/collections/12": detail,
      "/api/collections/12/rule": rule,
    });
    goToCollectionView(detail, "configure");
    renderWithQueryClient(CollectionPage);
    await fireEvent.input(await screen.findByLabelText("Criteria condition 1 MDBList lists"), {
      target: { value: "user/other" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Save and Sync" })).toBeEnabled(),
    );
    expect(screen.queryByRole("option", { name: "Manual selection" })).toBeNull();
  });

  it("uses the active artwork slot for external artwork links", async () => {
    mockFetchRoutes({
      "/api/collections/defaults": {},
      "/api/collections/capabilities": capabilities,
      "/api/collections/12/rule": rule,
      "/api/collections/groups": [],
      "/api/collections/12": { ...detail, tmdb_collection_id: 10 },
      "/api/collections/12/art/background/sources": { sources: {}, current_url: null },
    });
    goToCollectionView(detail, "art", "background");
    renderWithQueryClient(CollectionPage);
    expect(
      await screen.findByRole("tab", { name: "Background", selected: true }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "TMDb" })).toHaveAttribute(
      "href",
      "https://www.themoviedb.org/collection/10/images/backdrops",
    );
  });

  it("keeps one header and predictable record actions while switching sections", async () => {
    mockFetchRoutes({
      "/api/collections/defaults": {},
      "/api/collections/capabilities": capabilities,
      "/api/collections/12/rule": rule,
      "/api/collections/groups": [],
      "/api/collections/12": detail,
      "/api/library/items": { items: members, total: members.length },
      "/api/collections/12/art/poster/sources": { sources: {}, current_url: null },
      "/api/themes/search": { results: [] },
    });
    renderWithQueryClient(CollectionPage);
    const heading = await screen.findByRole("heading", { name: "Saga" });
    const recordActions = screen.getByRole("group", { name: "Record actions" });
    expect(screen.getAllByRole("main")).toHaveLength(1);
    expect(screen.getByRole("tab", { name: "Configure", selected: true })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Members" })).toBeInTheDocument();
    expect(screen.getByLabelText("TMDB collection ID")).toBeInTheDocument();
    await fireEvent.input(await screen.findByLabelText("Title"), {
      target: { value: "Unsaved title" },
    });
    expect(screen.getByLabelText("TMDB collection ID")).toBeInTheDocument();

    for (const section of ["Art", "Themes"] as const) {
      await fireEvent.click(screen.getByRole("tab", { name: section }));
      expect(await screen.findByRole("tab", { name: section, selected: true })).toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "Saga" })).toBe(heading);
      expect(screen.getByRole("group", { name: "Record actions" })).toBe(recordActions);
      expect(
        within(recordActions)
          .getAllByRole("button")
          .map((button) => button.title),
      ).toEqual(["Open Database Record", "Unmonitored - click to monitor", "Delete collection"]);
      expect(screen.queryByRole("tablist", { name: "Collection sections" })).toBeNull();
      expect(screen.queryByRole("region", { name: "TMDB collection match" })).toBeNull();
      if (section === "Art") {
        expect(screen.getByRole("tab", { name: "Poster", selected: true })).toBeInTheDocument();
        expect(
          await screen.findByRole("button", { name: "Paste URL & save as poster" }),
        ).toBeInTheDocument();
      } else {
        // The art tabs stay in place, with none selected outside the art view.
        const art = within(screen.getByRole("tablist", { name: "Art categories" }));
        expect(art.queryByRole("tab", { selected: true })).toBeNull();
        expect(screen.getByRole("link", { name: "Members" })).toBeInTheDocument();
        expect(screen.queryByRole("button", { name: /^Paste URL/ })).toBeNull();
      }
    }

    await fireEvent.click(screen.getByRole("tab", { name: "Configure" }));
    expect(await screen.findByLabelText("Title")).toHaveValue("Unsaved title");
  });

  it("round-trips collection art, rule, theme and settings views in both libraries", async () => {
    for (const media_type of ["movie", "show"] as const) {
      const target = { ...detail, media_type };
      for (const view of ["configure", "art", "themes"] as const) {
        goToCollectionView(target, view, "background");
        await waitFor(() => expect(routedCollectionView()).toBe(view));
        expect(routedCollectionId()).toBe(12);
        if (view === "art") expect(routedCollectionArtType()).toBe("background");
      }
    }
  });

  it("keeps metadata and rule drafts when monitoring changes from the header", async () => {
    mockFetchRoutes({
      "/api/collections/defaults": {},
      "/api/collections/capabilities": capabilities,
      "/api/collections/12/rule": rule,
      "/api/collections/groups": [],
      "/api/library/libraries": [{ id: "movies", title: "Movies", count: 2 }],
      "/api/library/items": { items: members, total: 2 },
      "/api/collections/12": detail,
      "/api/collections/12/monitored": { monitored: true },
    });
    goToCollectionView(detail, "configure");
    renderWithQueryClient(CollectionPage);
    await fireEvent.input(await screen.findByLabelText("Title"), {
      target: { value: "Unsaved title" },
    });
    await fireEvent.input(screen.getByLabelText("Summary"), {
      target: { value: "Unsaved summary" },
    });
    await fireEvent.input(screen.getByLabelText("Criteria condition 1 MDBList lists"), {
      target: { value: "draft/list" },
    });
    await fireEvent.click(screen.getByTitle("Unmonitored - click to monitor"));
    await screen.findByTitle("Monitored - click to unmonitor");
    expect(screen.getByLabelText("Criteria condition 1 MDBList lists")).toHaveValue("draft/list");

    expect(await screen.findByLabelText("Title")).toHaveValue("Unsaved title");
    expect(screen.getByLabelText("Summary")).toHaveValue("Unsaved summary");
  });
  it("offers a choice of deletion scope in a collapsed section", async () => {
    mockFetchRoutes({
      "/api/collections/defaults": {},
      "/api/collections/capabilities": capabilities,
      "/api/collections/12/rule": rule,
      "/api/collections/12": detail,
      "/api/collections/groups": [],
      "/api/library/libraries": [],
      "/api/library/items": { items: members, total: 2 },
    });
    renderWithQueryClient(CollectionPage);
    expect(await screen.findByRole("region", { name: "Collection setup" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Danger Zone" })).not.toBeInTheDocument();
    await fireEvent.click(
      screen.getByRole("button", { name: "Delete collection", expanded: false }),
    );
    expect(screen.getByRole("button", { name: "Delete from server only" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Delete from Overture and server" })).toBeEnabled();
  });

  it.each([
    ["server", "Delete from server only"],
    ["both", "Delete from Overture and server"],
  ] as const)("confirms the %s collection deletion target", async (target, label) => {
    const { calls } = mockFetchRoutes({
      "/api/collections/defaults": {},
      "/api/collections/capabilities": capabilities,
      "/api/collections/groups": ["Ungrouped"],
      "/api/collections/12": ({ init }: { init: RequestInit }) =>
        Response.json(init.method === "DELETE" ? { status: "deleted" } : detail),
      "/api/library/libraries": [],
      "/api/library/items": { items: members, total: 2 },
    });
    renderWithQueryClient(CollectionPage);
    await fireEvent.click(
      await screen.findByRole("button", { name: "Delete collection", expanded: false }),
    );
    await fireEvent.click(screen.getByRole("button", { name: label }));
    expect(calls.some((call) => call.init.method === "DELETE")).toBe(false);
    await answerConfirmation(true);
    await waitFor(() => {
      const request = calls.find((call) => call.init.method === "DELETE");
      expect(request).toBeDefined();
      expect(new URL(request!.url, "http://localhost").searchParams.get("target")).toBe(target);
    });
  });

  it("can return explicit collection settings to inherited group defaults", async () => {
    const { calls } = mockFetchRoutes({
      "/api/collections/defaults": { visible_home: true, visible_library: true },
      "/api/collections/capabilities": capabilities,
      "/api/collections/groups": ["Ungrouped"],
      "/api/collections/12": detail,
      "/api/collections/12/rule": rule,
    });
    renderWithQueryClient(CollectionPage);
    await screen.findByLabelText("Title");
    await fireEvent.click(screen.getByRole("button", { name: "Settings", expanded: false }));
    for (const [label, explicit] of [
      ["Sort", "title.asc"],
      ["Collection mode", "hide"],
      ["Collection filtering", "user"],
      ["Library recommended", "true"],
      ["Home", "false"],
      ["Shared users' home", "true"],
    ] as const) {
      const select = screen.getByLabelText(label);
      await fireEvent.change(select, { target: { value: explicit } });
      await fireEvent.change(select, { target: { value: "" } });
      expect(select).toHaveValue("");
    }
    for (const label of ["Sort title", "Summary"]) {
      const input = screen.getByLabelText(label);
      await fireEvent.input(input, { target: { value: "Custom" } });
      await fireEvent.input(input, { target: { value: "" } });
    }
    await fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      const saved = calls.find((call) => call.init.method === "PUT" && call.url.includes("/rule"));
      expect(JSON.parse(String(saved?.init.body))).toMatchObject({
        order_type: null,
        collection_mode: null,
        collection_filtering: null,
        visible_library: null,
        visible_home: null,
        visible_shared: null,
        sort_title_format: null,
        summary_format: null,
      });
    });
  });

  it("loads and saves group defaults without submitting the collection", async () => {
    const policy = {
      sync_mode: null,
      minimum_items: 3,
      delete_below_minimum: null,
      collection_mode: null,
      sort_title_format: null,
      auto_match_art: null,
      auto_match_theme: null,
    };
    const { calls } = mockFetchRoutes({
      "/api/collections/defaults": {},
      "/api/collections/capabilities": capabilities,
      "/api/collections/12/rule": rule,
      "/api/collections/12": { ...detail, collection_group: "Weekend" },
      "/api/collections/groups": ["Weekend"],
      "/api/library/libraries": [],
      "/api/library/items": { items: members, total: 2 },
      "/api/collections/group-policy": ({ init }: { init: RequestInit }) =>
        Response.json(init.method === "PUT" ? JSON.parse(String(init.body)) : policy),
    });
    renderWithQueryClient(GroupSettingsHarness, { group: "Weekend", mediaType: "movie" });
    await fireEvent.click(await screen.findByRole("button", { name: "Settings" }));
    await fireEvent.input(await screen.findByLabelText("Minimum members"), {
      target: { value: "2" },
    });
    await fireEvent.change(screen.getByLabelText("Below minimum"), {
      target: { value: "false" },
    });
    await fireEvent.input(screen.getByRole("textbox", { name: "Sort title" }), {
      target: { value: "+{title}" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls.some((call) => call.init.method === "PUT" && !call.url.includes("/rule"))).toBe(
        true,
      ),
    );
    const saved = calls.find((call) => call.init.method === "PUT");
    expect(saved?.url).toContain("/api/collections/group-policy?");
    expect(JSON.parse(String(saved?.init.body))).toMatchObject({
      minimum_items: 2,
      delete_below_minimum: false,
      sort_title_format: "+{title}",
    });
  });

  it("saves group defaults before explicitly applying them to the group", async () => {
    const { calls } = mockFetchRoutes({
      "/api/collections/defaults": {},
      "/api/collections/capabilities": capabilities,
      "/api/collections/12/rule": rule,
      "/api/collections/group-policy": ({ init }: { init: RequestInit }) =>
        Response.json(
          init.method === "PUT"
            ? JSON.parse(String(init.body))
            : { sort_title_format: "01_{title}", summary_format: null },
        ),
      "/api/collections/group-policy/apply": { collection_ids: [12, 13], errors: {} },
    });
    renderWithQueryClient(GroupSettingsHarness, { group: "Weekend", mediaType: "movie" });
    await fireEvent.click(await screen.findByRole("button", { name: "Save and Apply" }));
    await waitFor(() => expect(calls.some((call) => call.url.includes("/apply"))).toBe(true));
    expect(
      calls.filter((call) => call.init.method !== "GET").map((call) => call.init.method),
    ).toEqual(["PUT", "POST"]);
    expect(calls.some((call) => call.url.includes("/sync"))).toBe(false);
  });

  it("lists the titles the lists hold beyond the library and requests them", async () => {
    let requested: unknown = null;
    mockFetchRoutes({
      "/api/collections/defaults": {},
      "/api/collections/capabilities": capabilities,
      "/api/collections/12/rule": rule,
      "/api/collections/12": { ...detail, rule },
      "/api/collections/groups": [],
      "/api/library/libraries": [],
      "/api/library/items": { items: members, total: 2 },
      "/api/collections/12/missing": {
        titles: [
          { tmdb_id: 99, title: "Missing film", year: 2020, poster_url: null, requested: false },
          { tmdb_id: 98, title: "Wanted film", year: null, poster_url: null, requested: true },
        ],
        truncated: false,
        requestable: true,
      },
      "/api/collections/12/missing/request": ({ init }: { init: RequestInit }) => {
        requested = JSON.parse(String(init.body));
        return Response.json({ requested: 1, present: 0, errors: [] });
      },
    });
    goToCollectionView(detail, "configure");
    renderWithQueryClient(CollectionPage);
    await fireEvent.click(await screen.findByRole("button", { name: "Missing" }));
    const missing = within(screen.getByRole("region", { name: "Missing" }));
    expect(await missing.findByText("Missing film (2020)")).toBeInTheDocument();
    expect(missing.getByText("In Radarr")).toBeInTheDocument();
    await fireEvent.click(
      missing.getByRole("button", { name: "Request Missing film from Radarr" }),
    );
    await waitFor(() => expect(requested).toEqual({ tmdb_ids: [99] }));
  });
});
