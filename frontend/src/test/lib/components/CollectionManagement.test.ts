import { fireEvent, screen, waitFor, within } from "@testing-library/svelte";
import { beforeEach, describe, expect, it } from "vitest";
import CollectionGroupSettings from "../../../lib/components/CollectionGroupSettings.svelte";
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
import { mockFetchRoutes } from "../../helpers/fetch";
import { appSettings, collectionDetail, collectionRule, mediaItem } from "../../helpers/fixtures";
import { answerConfirmation } from "../../helpers/notifications";
import { renderWithQueryClient } from "../../helpers/render";

const members = [
  mediaItem({ id: 1, title: "First", library_id: "movies", server_item_id: "m1" }),
  mediaItem({ id: 2, title: "Second", library_id: "movies", server_item_id: "m2" }),
];
const third = mediaItem({ id: 3, title: "Third", library_id: "other", server_item_id: "m3" });
const detail = collectionDetail({
  id: 12,
  title: "Saga",
  library_id: "movies",
  members,
  child_count: 2,
});
const rule = collectionRule();

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
      "/api/collections/groups": [],
      "/api/collections/12": { ...detail, withheld: true },
    });
    renderWithQueryClient(CollectionPage);
    expect(await screen.findByText("Not on server")).toHaveAttribute(
      "title",
      "Collection kept in Overture and absent from the media server",
    );
  });

  it("removes members through the API and keeps the collection view in sync", async () => {
    const { calls } = mockFetchRoutes({
      "/api/collections/defaults": {},
      "/api/collections/groups": [],
      "/api/collections/12": detail,
      "/api/library/items": { items: members, total: 2 },
      "/api/collections/12/members": { ...detail, members: [members[1]], child_count: 1 },
    });
    renderWithQueryClient(CollectionPage);
    await fireEvent.click(await screen.findByRole("button", { name: "Resolved Members" }));
    await fireEvent.click(
      await screen.findByRole("button", { name: "Remove First from collection" }),
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "Remove First from collection" }),
      ).not.toBeInTheDocument(),
    );
    expect(calls.find((call) => call.init.method === "PUT")?.init.body).toBe(
      JSON.stringify({ member_ids: [2], order_type: "release" }),
    );
  });

  it("saves settings without losing nullable inheritance", async () => {
    let saved = false;
    mockFetchRoutes({
      "/api/collections/defaults": {},
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
    await fireEvent.click(screen.getByRole("button", { name: "Save Changes" }));
    await waitFor(() => expect(saved).toBe(true));
    expect(await screen.findByRole("heading", { name: "New saga" })).toBeInTheDocument();
  });

  it("saves rule overrides and runs a saved rule", async () => {
    const { calls } = mockFetchRoutes({
      "/api/collections/defaults": {},
      "/api/collections/groups": [],
      "/api/collections/12": { ...detail, rule },
      "/api/collections/12/rule": rule,
      "/api/collections/12/sync": { added: 1, removed: 0, skipped: false, deleted: false },
    });
    goToCollectionView(detail, "configure");
    renderWithQueryClient(CollectionPage);
    await fireEvent.change(await screen.findByLabelText("Sync strategy"), {
      target: { value: "append" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Save Changes" }));
    await waitFor(() => expect(calls.some((call) => call.init.method === "PUT")).toBe(true));
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
    await fireEvent.click(screen.getByRole("button", { name: "Sync Now" }));
    await waitFor(() =>
      expect(calls.some((call) => call.url.includes("/sync") && call.init.method === "POST")).toBe(
        true,
      ),
    );
  });

  it("saves an existing or custom group with the complete Configure draft", async () => {
    const { calls } = mockFetchRoutes({
      "/api/collections/defaults": {},
      "/api/collections/groups": ["default-decades", "Weekend"],
      "/api/collections/12": ({ init }: { init: RequestInit }) =>
        Response.json(init.method === "PUT" ? { ...detail, collection_group: "Weekend" } : detail),
    });
    renderWithQueryClient(CollectionPage);
    const group = await screen.findByLabelText("Collection Group");
    await screen.findByRole("option", { name: "Weekend" });
    await fireEvent.change(group, { target: { value: "Weekend" } });
    await fireEvent.click(screen.getByRole("button", { name: "Save Changes" }));
    await waitFor(() => expect(calls.some((call) => call.init.method === "PUT")).toBe(true));
    expect(
      JSON.parse(String(calls.find((call) => call.init.method === "PUT")?.init.body)),
    ).toMatchObject({ collection_group: "Weekend" });
  });

  it("only offers manual additions for manual and append collections", async () => {
    mockFetchRoutes({
      "/api/collections/defaults": {},
      "/api/collections/12": { ...detail, rule: { ...rule, sync_mode: "sync" } },
    });
    renderWithQueryClient(CollectionPage);
    await screen.findByRole("heading", { name: "Saga" });
    expect(screen.queryByLabelText("Add item")).toBeNull();
    expect(screen.getByLabelText("Member order")).toBeInTheDocument();
  });

  it("supports keyboard mode navigation while keeping both header boxes", async () => {
    mockFetchRoutes({
      "/api/collections/defaults": {},
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
      "/api/library/libraries": [{ id: "movies", title: "Movies", count: 2 }],
      "/api/library/items": { items: members, total: 2 },
      "/api/collections/groups": [],
    });
    await navigate("/movies/collections/new");
    const view = renderWithQueryClient(CollectionPage);
    await waitFor(() => expect(screen.getByLabelText("Library")).toHaveValue("movies"));
    expect(screen.getByLabelText("Title")).toHaveValue("");
    view.unmount();
    queryClient.clear();
    mockFetchRoutes({
      "/api/collections/defaults": {},
      "/api/library/libraries": [
        { id: "movies", title: "Movies", count: 2 },
        { id: "other", title: "Other", count: 1 },
      ],
      "/api/collections/groups": [],
    });
    await navigate("/movies/collections/new");
    renderWithQueryClient(CollectionPage);
    await screen.findByRole("option", { name: "Other" });
    expect(screen.getByLabelText("Library")).toHaveValue("");
  });

  it("edits an explicit TMDB ID without matching or automatic voting controls", async () => {
    const { calls } = mockFetchRoutes({
      "/api/collections/defaults": {},
      "/api/collections/12": { ...detail, tmdb_collection_id: 10 },
      "/api/collections/groups": [],
    });
    renderWithQueryClient(CollectionPage);
    const input = await screen.findByLabelText("TMDB collection ID");
    expect(input).toHaveValue(10);
    expect(screen.queryByRole("button", { name: "Reset to auto" })).toBeNull();
    await fireEvent.input(input, { target: { value: "99" } });
    await fireEvent.click(screen.getByRole("button", { name: "Save Changes" }));
    await waitFor(() => expect(calls.some((call) => call.init.method === "PUT")).toBe(true));
    expect(
      JSON.parse(String(calls.find((call) => call.init.method === "PUT")?.init.body)),
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
      "/api/collections/groups": [],
      "/api/library/libraries": [{ id: "movies", title: "Movies", count: 2 }],
      "/api/library/items": { items: members, total: 2 },
      "/api/collections": detail,
    });
    await navigate("/movies/collections/new");
    renderWithQueryClient(CollectionPage);
    await fireEvent.input(screen.getByLabelText("Title"), { target: { value: "Saga" } });
    await screen.findByRole("option", { name: "Movies" });
    await fireEvent.change(screen.getByLabelText("Library"), { target: { value: "movies" } });
    await fireEvent.click(screen.getByRole("button", { name: "TMDB titles" }));
    await fireEvent.change(screen.getByLabelText("TMDB movie IDs"), { target: { value: "11" } });
    await fireEvent.click(screen.getByRole("button", { name: "Create collection" }));
    await waitFor(() => expect(route.pathname).toBe("/movies/collections/12-saga"));
    expect(
      JSON.parse(String(calls.find((call) => call.init.method === "POST")?.init.body)),
    ).toMatchObject({
      title: "Saga",
      library_id: "movies",
      member_ids: [],
      rule: { builders: [{ type: "tmdb_item", tmdb_ids: [11] }] },
    });
  });

  it.each([
    { button: "Move First down", expected: [2, 1] },
    { button: "Move Second up", expected: [2, 1] },
  ])("reorders members using $button", async ({ button, expected }) => {
    const { calls } = mockFetchRoutes({
      "/api/collections/defaults": {},
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
    await fireEvent.click(await screen.findByRole("button", { name: "Resolved Members" }));
    expect(await screen.findByRole("button", { name: "Move First up" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Move Second down" })).toBeDisabled();
    await fireEvent.click(screen.getByRole("button", { name: button }));
    await waitFor(() => expect(calls.some((call) => call.init.method === "PUT")).toBe(true));
    expect(JSON.parse(String(calls.find((call) => call.init.method === "PUT")?.init.body))).toEqual(
      { member_ids: expected, order_type: "custom" },
    );
    await waitFor(() => expect(screen.getAllByRole("listitem")[0]).toHaveTextContent("Second"));
  });

  it("drops a member anywhere on another row at that row's position", async () => {
    const all = [...members, third];
    const { calls } = mockFetchRoutes({
      "/api/collections/defaults": {},
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
    await fireEvent.click(await screen.findByRole("button", { name: "Resolved Members" }));
    await fireEvent.dragStart(await screen.findByRole("button", { name: "Drag First to reorder" }));
    const target = screen
      .getAllByRole("listitem")
      .find((row) => within(row).queryByRole("button", { name: "Remove Third from collection" }));
    if (!target) throw new Error("Third collection member is missing");
    await fireEvent.drop(target);
    await waitFor(() => expect(calls.some((call) => call.init.method === "PUT")).toBe(true));
    expect(JSON.parse(String(calls.find((call) => call.init.method === "PUT")?.init.body))).toEqual(
      { member_ids: [2, 3, 1], order_type: "custom" },
    );
  });

  it("keeps member search trimmed and excludes collection members", async () => {
    mockFetchRoutes({
      "/api/collections/defaults": {},
      "/api/collections/groups": [],
      "/api/collections/12": { ...detail, members: [members[0]] },
      "/api/library/items": { items: members, total: 2 },
    });
    renderWithQueryClient(CollectionPage);
    await fireEvent.click(await screen.findByRole("button", { name: "Resolved Members" }));
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
    await screen.findByRole("option", { name: "Movies" });
    await fireEvent.change(screen.getByLabelText("Library"), { target: { value: "movies" } });
    await fireEvent.click(screen.getByRole("button", { name: "TMDB titles" }));
    await fireEvent.change(screen.getByLabelText("TMDB movie IDs"), { target: { value: "11" } });
    const submit = screen.getByRole("button", { name: "Create collection" });
    expect(submit).toBeDisabled();
    await fireEvent.input(screen.getByLabelText("Title"), { target: { value: "  Saga  " } });
    expect(submit).toBeEnabled();
    await fireEvent.change(screen.getByLabelText("Library"), { target: { value: "other" } });
    expect(screen.getByRole("button", { name: "Create collection" })).toBeEnabled();
    expect(screen.getByLabelText("TMDB movie IDs")).toHaveValue("11");
    await fireEvent.click(screen.getByRole("button", { name: "Create collection" }));
    await waitFor(() => expect(calls.some((call) => call.init.method === "POST")).toBe(true));
    expect(
      JSON.parse(String(calls.find((call) => call.init.method === "POST")?.init.body)),
    ).toMatchObject({
      title: "Saga",
      library_id: "other",
      member_ids: [],
      rule: { builders: [{ type: "tmdb_item", tmdb_ids: [11] }] },
    });
  });

  it("retries a refused collection creation from its error message", async () => {
    let attempts = 0;
    mockFetchRoutes({
      "/api/collections/defaults": {},
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
    await screen.findByRole("option", { name: "Movies" });
    await fireEvent.change(screen.getByLabelText("Library"), { target: { value: "movies" } });
    await fireEvent.click(screen.getByRole("button", { name: "TMDB titles" }));
    await fireEvent.change(screen.getByLabelText("TMDB movie IDs"), { target: { value: "11" } });
    await fireEvent.click(screen.getByRole("button", { name: "Create collection" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Create refused");
    await fireEvent.click(await screen.findByRole("button", { name: "Retry collection creation" }));
    await waitFor(() => expect(attempts).toBe(2));
    await waitFor(() => expect(route.pathname).toBe("/movies/collections/12-saga"));
  });

  it("shows a saved rule immediately without needing a live event", async () => {
    mockFetchRoutes({
      "/api/collections/defaults": {},
      "/api/collections/groups": [],
      "/api/library/libraries": [{ id: "movies", title: "Movies", count: 2 }],
      "/api/library/items": { items: members, total: 2 },
      "/api/collections/12": detail,
      "/api/collections/12/rule": ({ init }: { init: RequestInit }) =>
        Response.json(init.method === "DELETE" ? { status: "deleted" } : rule),
    });
    goToCollectionView(detail, "configure");
    renderWithQueryClient(CollectionPage);
    await fireEvent.change(await screen.findByLabelText("Source"), {
      target: { value: "builders" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "MDBList" }));
    await fireEvent.change(await screen.findByLabelText("MDBList list URL or ID"), {
      target: { value: "user/list" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Save Changes" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Sync Now" })).toBeEnabled());
    expect(screen.queryByRole("option", { name: "Manual selection" })).toBeNull();
  });

  it("uses the active artwork slot for external artwork links", async () => {
    mockFetchRoutes({
      "/api/collections/defaults": {},
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
        expect(screen.queryByRole("tablist", { name: "Art categories" })).toBeNull();
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
    await fireEvent.change(screen.getByLabelText("Source"), { target: { value: "builders" } });
    await fireEvent.click(screen.getByRole("button", { name: "MDBList" }));
    await fireEvent.change(await screen.findByLabelText("MDBList list URL or ID"), {
      target: { value: "draft/list" },
    });
    await fireEvent.click(screen.getByTitle("Unmonitored - click to monitor"));
    await screen.findByTitle("Monitored - click to unmonitor");
    expect(screen.getByLabelText("MDBList list URL or ID")).toHaveValue("draft/list");

    expect(await screen.findByLabelText("Title")).toHaveValue("Unsaved title");
    expect(screen.getByLabelText("Summary")).toHaveValue("Unsaved summary");
  });
  it("offers only the header delete action and no separate danger zone", async () => {
    mockFetchRoutes({
      "/api/collections/defaults": {},
      "/api/collections/12": detail,
      "/api/collections/groups": [],
      "/api/library/libraries": [],
      "/api/library/items": { items: members, total: 2 },
    });
    renderWithQueryClient(CollectionPage);
    expect(await screen.findByRole("region", { name: "Collection Setup" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Danger Zone" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Delete collection" })).toHaveLength(1);
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
      "/api/collections/12": { ...detail, collection_group: "Weekend" },
      "/api/collections/groups": ["Weekend"],
      "/api/library/libraries": [],
      "/api/library/items": { items: members, total: 2 },
      "/api/collections/group-policy": ({ init }: { init: RequestInit }) =>
        Response.json(init.method === "PUT" ? JSON.parse(String(init.body)) : policy),
    });
    renderWithQueryClient(CollectionGroupSettings, {
      group: "Weekend",
      mediaType: "movie",
      serverType: "plex",
    });
    await fireEvent.click(screen.getByRole("button", { name: "Group settings" }));
    await fireEvent.input(await screen.findByLabelText("Group Minimum members"), {
      target: { value: "2" },
    });
    await fireEvent.change(screen.getByLabelText("Group Below minimum"), {
      target: { value: "false" },
    });
    await fireEvent.click(screen.getByLabelText("Default sort title template"));
    await fireEvent.input(screen.getByRole("textbox", { name: /^Group sort title template/ }), {
      target: { value: "+{title}" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Save group defaults" }));
    await waitFor(() => expect(calls.some((call) => call.init.method === "PUT")).toBe(true));
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
      "/api/collections/group-policy": ({ init }: { init: RequestInit }) =>
        Response.json(
          init.method === "PUT"
            ? JSON.parse(String(init.body))
            : { sort_title_format: "01_{title}", summary_format: null },
        ),
      "/api/collections/group-policy/apply": { collection_ids: [12, 13], errors: {} },
    });
    renderWithQueryClient(CollectionGroupSettings, {
      group: "Weekend",
      mediaType: "movie",
      serverType: "plex",
    });
    await fireEvent.click(screen.getByRole("button", { name: "Group settings" }));
    await screen.findByRole("button", { name: "Save & Apply to group" });
    await fireEvent.click(screen.getByRole("button", { name: "Save & Apply to group" }));
    await waitFor(() => expect(calls.some((call) => call.url.includes("/apply"))).toBe(true));
    expect(
      calls.filter((call) => call.init.method !== "GET").map((call) => call.init.method),
    ).toEqual(["PUT", "POST"]);
    expect(calls.some((call) => call.url.includes("/sync"))).toBe(false);
  });

  it("reuses the TMDB roster grid to show owned and missing source titles", async () => {
    mockFetchRoutes({
      "/api/collections/defaults": {},
      "/api/collections/12": { ...detail, tmdb_collection_id: 10 },
      "/api/collections/groups": [],
      "/api/library/libraries": [],
      "/api/library/items": { items: members, total: 2 },
      "/api/tmdb/collections/10": {
        tmdb_id: 10,
        title: "Saga",
        items: [
          {
            kind: "item",
            media_type: "movie",
            tmdb_id: 11,
            title: "Owned source movie",
            existing_item_id: 1,
          },
          {
            kind: "item",
            media_type: "movie",
            tmdb_id: 99,
            title: "Missing source movie",
            existing_item_id: null,
          },
        ],
      },
    });
    renderWithQueryClient(CollectionPage);
    const roster = await screen.findByRole("region", { name: "Source roster" });
    expect(await within(roster).findByText("Owned source movie")).toBeInTheDocument();
    expect(within(roster).getByText("Missing source movie")).toBeInTheDocument();
    expect(within(roster).getAllByText("In library")).toHaveLength(1);
  });
});
