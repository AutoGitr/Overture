import { fireEvent, screen, waitFor, within } from "@testing-library/svelte";
import { beforeEach, describe, expect, it } from "vitest";
import CollectionPage from "../../../lib/router/pages/CollectionPage.svelte";
import { queryClient } from "../../../lib/rest/queryClient";
import { goToCollectionView, navigate, route, sidebarGroup } from "../../../lib/router/routes";
import { settingsState } from "../../../lib/stores/settingsState.svelte";
import { mockFetchRoutes } from "../../helpers/fetch";
import { appSettings, collectionDetail, collectionRule, mediaItem } from "../../helpers/fixtures";
import { renderWithQueryClient } from "../../helpers/render";

const member = mediaItem({ id: 1, title: "First", library_id: "movies", server_item_id: "m1" });
const detail = collectionDetail({ id: 12, title: "Saga", library_id: "movies", members: [member] });
const libraries = [
  { id: "movies", title: "Movies", count: 1 },
  { id: "other", title: "Other movies", count: 1 },
];

function mockPage(overrides: Record<string, unknown> = {}) {
  return mockFetchRoutes({
    "/api/library/libraries": libraries,
    "/api/library/items": { items: [member], total: 1 },
    "/api/collections/groups": ["Franchises"],
    "/api/collections/defaults": {
      minimum_items: 1,
      sort_title_format: "01_{title}",
      summary_format: "From {group}",
    },
    "/api/collections/12": detail,
    "/api/collections": detail,
    "/api/collections/12/rule": collectionRule(),
    ...overrides,
  });
}

async function createPage() {
  await navigate("/movies/collections/new");
  renderWithQueryClient(CollectionPage);
  await screen.findByRole("option", { name: "Movies" });
}

async function chooseSource(source: string) {
  if (source === "discovery") {
    await fireEvent.change(screen.getByLabelText("Type"), { target: { value: "preset" } });
    await fireEvent.change(screen.getByLabelText("Preset"), { target: { value: "discovery" } });
  } else {
    if (!screen.queryByLabelText("Source"))
      await fireEvent.change(screen.getByLabelText("Type"), { target: { value: "custom" } });
    await fireEvent.change(screen.getByLabelText("Source"), { target: { value: source } });
  }
}

describe("collection setup flow", () => {
  beforeEach(() => {
    queryClient.clear();
    settingsState.load(appSettings({ media_server: "plex", collections_supported: true }));
  });

  it("keeps only universal fields in Setup and adapts the section shortcuts", async () => {
    mockPage();
    await createPage();
    const setup = within(screen.getByRole("region", { name: "Collection Setup" }));
    expect(screen.queryByRole("radiogroup", { name: "Collection scope" })).toBeNull();
    expect(screen.queryByRole("option", { name: "Manual selection" })).toBeNull();
    for (const name of ["Library", "Source", "Title", "Collection Group"]) {
      expect(setup.getByLabelText(name)).toBeInTheDocument();
    }
    expect(setup.queryByLabelText("TMDB collection ID")).toBeNull();
    expect(screen.getByRole("link", { name: "Content" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Initial members" })).toBeNull();
    for (const name of ["Setup", "Content", "Display", "Schedule"]) {
      const link = screen.getByRole("link", { name });
      const target = link.getAttribute("href")?.slice(1);
      expect(document.getElementById(target ?? "")).not.toBeNull();
    }
  });

  it("starts with only Setup and Content expanded and opens sections through navigation", async () => {
    mockPage();
    await createPage();
    for (const name of ["Collection Setup", "Content"])
      expect(screen.getByRole("button", { name })).toHaveAttribute("aria-expanded", "true");
    for (const name of ["Display", "Schedule"])
      expect(screen.getByRole("button", { name })).toHaveAttribute("aria-expanded", "false");
    await fireEvent.click(screen.getByRole("link", { name: "Display" }));
    expect(screen.getByRole("button", { name: "Display" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    await waitFor(() =>
      expect(screen.getByLabelText("Sort title")).toHaveAttribute("placeholder", "01_{title}"),
    );
    await fireEvent.input(screen.getByLabelText("Sort title"), { target: { value: "02_{title}" } });
    expect(screen.getByLabelText("Sort title")).toHaveValue("02_{title}");
  });

  it("previews library presets and creates only the selected entries as editable rules", async () => {
    const { calls } = mockPage({
      "/api/collections/presets/preview": [
        { key: "1990", title: "1990s", member_count: 3 },
        { key: "2000", title: "2000s", member_count: 4 },
      ],
      "/api/collections/presets": { collection_ids: [13], errors: {} },
    });
    await createPage();
    await fireEvent.change(screen.getByLabelText("Library"), { target: { value: "movies" } });
    await fireEvent.change(screen.getByLabelText("Type"), { target: { value: "preset" } });
    expect(screen.queryByLabelText("Source")).toBeNull();
    expect(screen.getByLabelText("Preset")).toHaveDisplayValue("Decades");
    await fireEvent.change(screen.getByLabelText("Collection Group"), {
      target: { value: "Franchises" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Preview collections" }));
    await fireEvent.click(await screen.findByRole("checkbox", { name: "1990s (3 members)" }));
    await fireEvent.click(
      within(screen.getByRole("group", { name: "Collection form actions" })).getByRole("button", {
        name: "Create selected collections",
      }),
    );
    await waitFor(() => expect(route.pathname).toBe("/movies/collections"));
    const request = calls.find((call) => call.url === "/api/collections/presets");
    const body = JSON.parse(String(request?.init.body));
    expect(body).toMatchObject({ preset: "decades", library_id: "movies", keys: ["2000"] });
    expect(body.policy).not.toHaveProperty("builders");
    expect(body.policy).not.toHaveProperty("smart_filter");
    expect(sidebarGroup()).toBe("Franchises");
  });

  it("requires a fresh preview when changing the preset or library", async () => {
    mockPage({
      "/api/collections/presets/preview": [{ key: "1990", title: "1990s", member_count: 1 }],
    });
    await createPage();
    await fireEvent.change(screen.getByLabelText("Library"), { target: { value: "movies" } });
    await fireEvent.change(screen.getByLabelText("Type"), { target: { value: "preset" } });
    await fireEvent.click(screen.getByRole("button", { name: "Preview collections" }));
    await screen.findByRole("checkbox", { name: "1990s (1 member)" });
    await fireEvent.change(screen.getByLabelText("Library"), { target: { value: "other" } });
    expect(screen.queryByRole("checkbox", { name: /1990s/ })).toBeNull();
    expect(
      within(screen.getByRole("group", { name: "Collection form actions" })).getByRole("button"),
    ).toBeDisabled();
  });

  it("uses Setup's library and group for discovery and restores the single collection draft", async () => {
    mockPage();
    await createPage();
    await fireEvent.input(screen.getByLabelText("Title"), { target: { value: "My draft" } });
    await fireEvent.change(screen.getByLabelText("Library"), { target: { value: "movies" } });
    await chooseSource("discovery");
    expect(screen.getByRole("region", { name: "Collection Setup" })).toBeInTheDocument();
    expect(screen.getByLabelText("Title")).toBeDisabled();
    expect(screen.getByLabelText("Preset")).toHaveDisplayValue("TMDB franchises");
    expect(screen.getAllByLabelText("Library")).toHaveLength(1);
    expect(screen.queryByRole("link", { name: "Members" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Display" })).toBeNull();
    expect(screen.getByRole("button", { name: "Discover & Create Collections" })).toBeDisabled();
    await fireEvent.change(screen.getByLabelText("Collection Group"), {
      target: { value: "Franchises" },
    });
    expect(screen.getByRole("button", { name: "Discover & Create Collections" })).toBeEnabled();
    await chooseSource("builders");
    expect(screen.getByLabelText("Title")).toHaveValue("My draft");
    expect(screen.getByLabelText("Library")).toHaveValue("movies");
  });

  it("discovers from the selected library, preserves other group defaults, and uses one submit action", async () => {
    const { calls } = mockPage({
      "/api/collections/group-policy": ({ init }: { init: RequestInit }) =>
        Response.json(
          init.method === "PUT"
            ? JSON.parse(String(init.body))
            : { visible_home: true, summary_format: "Keep {title}" },
        ),
      "/api/collections/group-policy/sync": { status: "ok" },
    });
    await createPage();
    await fireEvent.change(screen.getByLabelText("Library"), { target: { value: "other" } });
    await chooseSource("discovery");
    await fireEvent.change(screen.getByLabelText("Collection Group"), {
      target: { value: "Franchises" },
    });
    await fireEvent.input(screen.getByLabelText(/Minimum members/), { target: { value: "3" } });
    await fireEvent.input(screen.getByLabelText(/Sync interval/), { target: { value: "168" } });
    await fireEvent.click(screen.getByRole("button", { name: "Discover & Create Collections" }));
    await waitFor(() => expect(route.pathname).toBe("/movies/collections"));
    expect(
      JSON.parse(String(calls.find((call) => call.init.method === "PUT")?.init.body)),
    ).toMatchObject({
      minimum_items: 3,
      sync_interval_hours: 168,
      visible_home: true,
      summary_format: "Keep {title}",
      dynamic_tmdb: { enabled: true, library_id: "other" },
    });
    expect(
      calls.some((call) => call.url.includes("group-policy/sync") && call.init.method === "POST"),
    ).toBe(true);
    expect(
      calls.some((call) => call.url === "/api/collections" && call.init.method === "POST"),
    ).toBe(false);
  });

  it("switching from smart to dynamic sources submits regular membership without a hidden smart filter", async () => {
    const source = "builders";
    const { calls } = mockPage();
    await createPage();
    await fireEvent.change(screen.getByLabelText("Library"), { target: { value: "movies" } });
    await fireEvent.input(screen.getByLabelText("Title"), { target: { value: "Saga" } });
    await chooseSource("smart");
    await fireEvent.input(screen.getByLabelText(/Managed Plex label/), {
      target: { value: "Requests" },
    });
    await chooseSource(source);
    if (source === "builders") {
      await fireEvent.click(screen.getByRole("button", { name: "TMDB titles" }));
      await fireEvent.change(screen.getByLabelText("TMDB movie IDs"), {
        target: { value: "550" },
      });
    }
    await fireEvent.click(screen.getByRole("button", { name: "Create collection" }));
    await waitFor(() => expect(calls.some((call) => call.init.method === "POST")).toBe(true));
    const body = JSON.parse(String(calls.find((call) => call.init.method === "POST")?.init.body));
    expect(body.kind).toBe("regular");
    expect(body.rule).toEqual(expect.objectContaining({ smart_filter: null, managed_label: null }));
    expect(body.member_ids).toEqual([]);
  });

  it("creates a smart collection from Radarr tags and an unwatched filter and true or false conditions", async () => {
    const { calls } = mockPage();
    await createPage();
    await fireEvent.change(screen.getByLabelText("Library"), { target: { value: "movies" } });
    await fireEvent.input(screen.getByLabelText("Title"), { target: { value: "Requests" } });
    await chooseSource("smart");
    await fireEvent.input(screen.getByLabelText(/Managed Plex label/), {
      target: { value: "Requests" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Radarr tags" }));
    await fireEvent.change(screen.getByLabelText("Radarr tags"), { target: { value: "request" } });
    await fireEvent.click(screen.getByRole("button", { name: "Condition" }));
    await fireEvent.change(screen.getByLabelText("Smart collection criteria field 1"), {
      target: { value: "unplayed" },
    });
    const condition = screen.getByLabelText("Smart collection criteria value 1");
    expect(within(condition).getByRole("option", { name: "true" })).toBeInTheDocument();
    expect(within(condition).getByRole("option", { name: "false" })).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Create collection" }));
    await waitFor(() => expect(calls.some((call) => call.init.method === "POST")).toBe(true));
    expect(
      JSON.parse(String(calls.find((call) => call.init.method === "POST")?.init.body)),
    ).toMatchObject({
      kind: "smart",
      member_ids: [],
      rule: {
        managed_label: "Requests",
        builders: [{ type: "radarr_tag", tags: ["request"] }],
        smart_filter: { filter_group: { conditions: [{ field: "unplayed", value: true }] } },
      },
    });
  });

  it("creates from multiple TMDB lists with unified metadata fields and group selection", async () => {
    const { calls } = mockPage();
    await createPage();
    await fireEvent.change(screen.getByLabelText("Library"), { target: { value: "movies" } });
    await fireEvent.input(screen.getByLabelText("Title"), { target: { value: "Favorites" } });
    await fireEvent.change(screen.getByLabelText("Collection Group"), {
      target: { value: "Franchises" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "TMDB lists" }));
    await fireEvent.change(screen.getByLabelText("TMDB list IDs"), { target: { value: "42, 84" } });
    await fireEvent.input(screen.getByLabelText("Sort title"), { target: { value: "01_{title}" } });
    await fireEvent.input(screen.getByLabelText("Summary"), {
      target: { value: "Favorites in {group}" },
    });
    expect(screen.queryByLabelText("Apply sort title template")).toBeNull();
    expect(screen.queryByLabelText("Summary template")).toBeNull();
    await fireEvent.click(screen.getByRole("button", { name: "Create collection" }));
    await waitFor(() => expect(calls.some((call) => call.init.method === "POST")).toBe(true));
    const call = calls.find((call) => call.init.method === "POST");
    expect(JSON.parse(String(call?.init.body))).toMatchObject({
      sort_title: null,
      summary: null,
      sort_title_format: "01_{title}",
      summary_format: "Favorites in {group}",
      collection_group: "Franchises",
      rule: { builders: [{ type: "tmdb_list", list_ids: [42, 84] }] },
    });
  });

  it("recognizes imported smart collections and keeps server-controlled members read-only", async () => {
    const smart = { ...detail, kind: "smart" as const, rule: null };
    mockPage({ "/api/collections/12": smart });
    goToCollectionView(smart, "configure");
    renderWithQueryClient(CollectionPage);
    expect(await screen.findByLabelText("Source")).toHaveValue("smart");
    expect(screen.queryByLabelText(/Smart sort order/)).toBeNull();
    expect(screen.getByLabelText("Manage smart filter in Overture")).not.toBeChecked();
    expect(screen.queryByLabelText("Add item")).toBeNull();
    expect(screen.queryByLabelText("Sort members")).toBeNull();
    expect(screen.queryByRole("button", { name: "Remove First from collection" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Move First down" })).toBeNull();
  });

  it("preserves an imported Plex filter when saving display changes and can explicitly adopt it", async () => {
    const smart = { ...detail, kind: "smart" as const, rule: null };
    const { calls } = mockPage({
      "/api/collections/12": ({ init }: { init: RequestInit }) =>
        Response.json(
          init.method === "PUT" ? { ...smart, ...JSON.parse(String(init.body)) } : smart,
        ),
    });
    goToCollectionView(smart, "configure");
    renderWithQueryClient(CollectionPage);
    await fireEvent.input(await screen.findByLabelText("Title"), {
      target: { value: "Renamed smart collection" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Save Changes" }));
    await waitFor(() => expect(calls.some((call) => call.init.method === "PUT")).toBe(true));
    expect(calls.some((call) => call.url.includes("/rule"))).toBe(false);
    await waitFor(() => expect(screen.getByRole("button", { name: "Save Changes" })).toBeEnabled());
    await fireEvent.click(screen.getByLabelText("Manage smart filter in Overture"));
    expect(screen.getByLabelText(/Smart sort order/)).toBeInTheDocument();
    await fireEvent.input(screen.getByLabelText(/Managed Plex label/), {
      target: { value: "Favorites" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Save Changes" }));
    await waitFor(() =>
      expect(calls.some((call) => call.url.includes("/rule") && call.init.method === "PUT")).toBe(
        true,
      ),
    );
  });

  it.each(["jellyfin", "emby"] as const)(
    "offers only supported source types for %s",
    async (server) => {
      settingsState.load(appSettings({ media_server: server, collections_supported: true }));
      mockPage();
      await createPage();
      expect(screen.queryByRole("option", { name: "Plex smart filter" })).toBeNull();
      expect(screen.queryByLabelText("Visibility")).toBeNull();
      expect(screen.queryByRole("option", { name: "Source / custom order" })).toBeNull();
      await chooseSource("builders");
      expect(screen.getByRole("button", { name: "MDBList" })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /IMDb|Trakt|TVDB/ })).toBeNull();
    },
  );
});
