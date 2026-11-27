import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/svelte";
import { beforeEach, describe, expect, it } from "vitest";
import CollectionPage from "../../../lib/router/pages/CollectionPage.svelte";
import { queryClient } from "../../../lib/rest/queryClient";
import { goToCollectionView, navigate, route, sidebarGroup } from "../../../lib/router/routes";
import { settingsState } from "../../../lib/stores/settingsState.svelte";
import { mockFetchRoutes } from "../../helpers/fetch";
import {
  appSettings,
  collectionCapabilities,
  collectionDetail,
  collectionRule,
  mediaItem,
  mediaServers,
} from "../../helpers/fixtures";
import { chooseOption, renderWithQueryClient } from "../../helpers/render";
import type { PresetListing } from "../../../generated/rest/types.gen";
import { uiState } from "../../../lib/stores/uiState.svelte";
import { syncSelection } from "../../../lib/stores/syncSelection.svelte";

const member = mediaItem({ id: 1, title: "First", library_id: "movies", server_item_id: "m1" });
const detail = collectionDetail({
  id: 12,
  title: "Saga",
  library_ids: ["movies"],
  member_ids: [member.id],
});
const libraries = [
  { id: "movies", title: "Movies", media_type: "movie", server_id: 1, count: 1 },
  { id: "other", title: "Other movies", media_type: "movie", server_id: 1, count: 1 },
];
function mockPage(overrides: Record<string, unknown> = {}) {
  return mockFetchRoutes({
    "/api/library/libraries": libraries,
    "/api/library/items": { items: [member], total: 1 },
    "/api/collection-groups": [{ name: "Franchises", set: null }],
    "/api/collections/defaults": {
      minimum_items: 1,
      sort_title_format: "01_{title}",
      summary_format: "From {group}",
    },
    "/api/collections/capabilities": collectionCapabilities(),
    "/api/collections/12": detail,
    "/api/collections": ({ init }: { init: RequestInit }) =>
      Response.json(init.method === "POST" ? detail : []),
    "/api/collections/12/rule": collectionRule(),
    "/api/collections/presets": { generated_at: null, presets: [], error: null },
    ...overrides,
  });
}

async function createPage() {
  await navigate("/collections/new");
  renderWithQueryClient(CollectionPage);
  await fireEvent.click(await screen.findByRole("checkbox", { name: "Movies" }));
}

function postedBody(calls: { url: string; init: RequestInit }[], path: string) {
  const call = calls.find(
    (entry) => entry.url.split("?")[0] === path.split("?")[0] && entry.init.method !== "GET",
  );
  return JSON.parse(String(call?.init.body));
}

const ACTION = {
  mode: "all",
  conditions: [{ kind: "field", field: "genre", operator: "is", value: "Holiday" }],
  groups: [],
};

/** A preset as the gallery lists it, with only the fields the form reads. */
const SEASONAL = {
  id: "holidays",
  preset: {
    id: "holidays",
    title: "Holidays",
    description: "Holiday titles.",
    category: "seasonal",
    tags: [],
    media_types: ["movie"],
  },
  file: {
    preset_version: 1,
    preset: null,
    groups: [
      { name: "Holidays", generator: null, minimum_items: 2, delete_when_inactive: null },
      {
        name: "Decades",
        minimum_items: 3,
        generator: {
          dimension: "decade",
          media_types: ["movie"],
          title_format: "{value}s",
          criteria: { mode: "all", conditions: [], groups: [] },
        },
      },
    ],
    collections: [
      {
        title: "Christmas",
        collection_group: "Holidays",
        active_start_mmdd: "12-01",
        active_end_mmdd: "12-26",
        criteria: { movie: ACTION },
        minimum_items: null,
        smart: false,
        limit: null,
        art: { poster: { url: "https://example.org/christmas.jpg", style: "individual" } },
      },
    ],
  },
  setup: ["Set TMDB_READ_ACCESS_TOKEN to use TMDB"],
  problem: null,
  preview_url: null,
} as unknown as PresetListing;

/** Choose exactly one library in Setup's Libraries. */
async function onlyLibrary(scope: Pick<typeof screen, "getByRole">, name: string) {
  const libraries = within(scope.getByRole("group", { name: "Libraries" }));
  const chosen = libraries.getByRole("checkbox", { name });
  for (const box of libraries.getAllByRole<HTMLInputElement>("checkbox"))
    if (box.checked !== (box === chosen)) await fireEvent.click(box);
}

describe("collection setup flow", () => {
  beforeEach(() => {
    queryClient.clear();
    settingsState.load(
      appSettings({ media_servers: mediaServers("plex"), collections_supported: true }),
    );
  });

  it("adapts Setup to a collection or a set, with no tab rows while new", async () => {
    mockPage();
    await createPage();
    const setup = within(screen.getByRole("region", { name: "Collection setup" }));
    expect(setup.getByRole("group", { name: "Libraries" })).toBeInTheDocument();
    for (const name of ["Title", "Group"]) {
      expect(setup.getByLabelText(name)).toBeInTheDocument();
    }
    expect(setup.queryByLabelText(/^Start from/)).toBeNull();
    expect(setup.queryByLabelText("Save as preset")).toBeNull();
    expect(setup.queryByLabelText("Split by")).toBeNull();
    expect(setup.queryByLabelText("TMDB collection ID")).toBeNull();
    expect(screen.queryByRole("tablist", { name: "Detail modes" })).toBeNull();
    expect(screen.queryByRole("navigation", { name: "Configure sections" })).toBeNull();

    await fireEvent.click(setup.getByLabelText("One per value"));
    expect(setup.queryByLabelText("Title")).toBeNull();
    expect(setup.getByRole("combobox", { name: /^Group/ })).toBeRequired();
    // Both kinds share their sections; a set's Title is a template.
    for (const name of ["Collection content", "Collection settings", "Collection schedule"])
      expect(screen.getByRole("region", { name })).toBeInTheDocument();
    expect(setup.getByLabelText(/^Title template/)).toHaveValue("{value}s");
    // Create comes first, then Split by, which names the group.
    const labels = setup
      .getAllByText(/^(Create|Split by|Libraries)$/)
      .map((label) => label.textContent);
    expect(labels).toEqual(["Create", "Split by", "Libraries"]);
    expect(setup.getByLabelText("Split by")).toHaveTextContent("Decades");
    expect(setup.getByRole("combobox", { name: /^Group/ })).toHaveValue("Decades");
  });

  it("fills a set from a preset in every library of its kind, on every server", async () => {
    settingsState.load(
      appSettings({ media_servers: mediaServers("plex", "jellyfin"), collections_supported: true }),
    );
    const { calls } = mockPage({
      "/api/library/libraries": [
        ...libraries,
        { id: "jf-movies", title: "Movies", media_type: "movie", server_id: 2, count: 1 },
        { id: "jf-shows", title: "Shows", media_type: "show", server_id: 2, count: 1 },
      ],
      "/api/collections/presets": { generated_at: null, presets: [SEASONAL], error: null },
      "/api/collection-groups/Decades": ({ init }: { init: RequestInit }) =>
        Response.json(init.method === "PUT" ? JSON.parse(String(init.body)) : {}),
    });
    await navigate("/collections/new");
    renderWithQueryClient(CollectionPage);
    const setup = within(screen.getByRole("region", { name: "Collection setup" }));
    // Presets come first, grouped by category, then what to create.
    const labels = setup.getAllByText(/^(Presets|Create)$/).map((label) => label.textContent);
    expect(labels).toEqual(["Presets", "Create"]);
    await chooseOption(await setup.findByLabelText("Presets"), /^Decades/);

    expect(setup.getByLabelText("One per value")).toBeChecked();
    expect(setup.getByRole("combobox", { name: /^Group/ })).toHaveValue("Decades");
    // Every movie library on both servers, and no show library.
    const boxes = within(setup.getByRole("group", { name: "Libraries" }));
    expect(
      boxes.getAllByRole("checkbox", { name: /Movies|Other movies/, checked: true }),
    ).toHaveLength(3);
    expect(boxes.queryAllByRole("checkbox", { name: "Shows", checked: true })).toHaveLength(0);
    expect(setup.getByText("Set TMDB_READ_ACCESS_TOKEN to use TMDB")).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(sidebarGroup()).toBe("Decades"));
    expect(postedBody(calls, "/api/collection-groups/Decades")).toMatchObject({
      minimum_items: 3,
      generator: { dimension: "decade", library_ids: ["movies", "other", "jf-movies"] },
    });
    // OvertureDB's later changes to the set are tracked.
    await waitFor(() =>
      expect(postedBody(calls, "/api/collections/presets/uses")).toEqual({
        group: "Decades",
        preset_id: "holidays",
        item: "Decades",
      }),
    );
  });

  it("fills a collection from a preset, its group's missing defaults and its art", async () => {
    const { calls } = mockPage({
      "/api/collections/presets": { generated_at: null, presets: [SEASONAL], error: null },
      "/api/collection-groups/Holidays": ({ init }: { init: RequestInit }) =>
        Response.json(
          init.method === "PUT"
            ? JSON.parse(String(init.body))
            : { minimum_items: null, delete_when_inactive: true },
        ),
      "/api/collections/12/art/poster": { status: "ok" },
    });
    await navigate("/collections/new");
    renderWithQueryClient(CollectionPage);
    const setup = within(screen.getByRole("region", { name: "Collection setup" }));
    await chooseOption(await setup.findByLabelText("Presets"), /^Christmas/);

    expect(setup.getByLabelText("Title")).toHaveValue("Christmas");
    expect(setup.getByText(/Saving gives the group "Holidays"/)).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(calls.some((call) => call.url === "/api/collections/12/art/poster")).toBe(true),
    );
    // The group keeps what it set; only what it leaves at Default is filled.
    expect(postedBody(calls, "/api/collection-groups/Holidays")).toEqual({
      minimum_items: 2,
      delete_when_inactive: true,
    });
    const created = postedBody(calls, "/api/collections");
    expect(created).toMatchObject({
      title: "Christmas",
      collection_group: "Holidays",
      active_start_mmdd: "12-01",
      rule: {
        libraries: [
          { library_id: "movies", criteria: ACTION },
          { library_id: "other", criteria: ACTION },
        ],
      },
    });
    // How it is shown is this install's own, so the collection inherits it.
    expect(created).not.toHaveProperty("visible_home");
    expect(postedBody(calls, "/api/collections/12/art/poster")).toEqual({
      url: "https://example.org/christmas.jpg",
      poster_style: "individual",
    });
    expect(postedBody(calls, "/api/collections/presets/uses")).toEqual({
      collection_id: 12,
      preset_id: "holidays",
      item: "Christmas",
    });
  });

  it("adds several presets at once, each as choosing it alone and saving would", async () => {
    const { calls } = mockPage({
      "/api/collections/presets": { generated_at: null, presets: [SEASONAL], error: null },
      "/api/collection-groups/Decades": ({ init }: { init: RequestInit }) =>
        Response.json(init.method === "PUT" ? JSON.parse(String(init.body)) : {}),
      "/api/collection-groups/Holidays": ({ init }: { init: RequestInit }) =>
        Response.json(
          init.method === "PUT" ? JSON.parse(String(init.body)) : { minimum_items: null },
        ),
      "/api/collections/12/art/poster": { status: "ok" },
    });
    await navigate("/collections/new");
    renderWithQueryClient(CollectionPage);
    const setup = within(screen.getByRole("region", { name: "Collection setup" }));
    await setup.findByLabelText("Presets");
    await fireEvent.click(setup.getByRole("button", { name: "Choose several" }));
    const list = within(setup.getByRole("group", { name: "Presets to add" }));
    await fireEvent.click(await list.findByRole("checkbox", { name: /^Decades/ }));
    await fireEvent.click(list.getByRole("checkbox", { name: /^Christmas/ }));
    await fireEvent.click(setup.getByRole("button", { name: "Add 2" }));

    await waitFor(() =>
      expect(
        calls.filter(
          (call) => call.url === "/api/collections/presets/uses" && call.init.method === "POST",
        ),
      ).toHaveLength(2),
    );
    // Saving only records them; it never reads every collection's preset.
    expect(
      calls.some((call) => call.url === "/api/collections/presets/uses" && !call.init.method),
    ).toBe(false);
    expect(postedBody(calls, "/api/collection-groups/Decades")).toMatchObject({
      generator: { dimension: "decade", library_ids: ["movies", "other"] },
    });
    expect(postedBody(calls, "/api/collections")).toMatchObject({
      title: "Christmas",
      collection_group: "Holidays",
    });
  });

  it("offers a loaded file's collections and sets beside the presets", async () => {
    const { calls } = mockPage({
      "/api/collections/presets/file": { ...SEASONAL, id: "file", preset: null, setup: [] },
    });
    await navigate("/collections/new");
    renderWithQueryClient(CollectionPage);
    const setup = within(screen.getByRole("region", { name: "Collection setup" }));
    const file = new File([JSON.stringify(SEASONAL.file)], "export.json", {
      type: "application/json",
    });
    await fireEvent.change(setup.getByLabelText("Load file"), { target: { files: [file] } });
    await waitFor(() =>
      expect(calls.some((call) => call.url === "/api/collections/presets/file")).toBe(true),
    );
    await fireEvent.click(setup.getByLabelText("Presets"));
    const listbox = await screen.findByRole("listbox");
    expect(within(listbox).getByText("From file")).toBeInTheDocument();
    await fireEvent.click(within(listbox).getByRole("option", { name: /^Christmas/ }));
    expect(setup.getByLabelText("Title")).toHaveValue("Christmas");
  });

  it("starts with only Setup and Content expanded and opens sections from any view", async () => {
    mockPage();
    goToCollectionView(detail, "art");
    renderWithQueryClient(CollectionPage);
    await fireEvent.click(await screen.findByRole("link", { name: "Settings" }));
    for (const name of ["Setup", "Content"])
      expect(await screen.findByRole("button", { name })).toHaveAttribute("aria-expanded", "true");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Settings" })).toHaveAttribute(
        "aria-expanded",
        "true",
      ),
    );
    expect(screen.getByRole("region", { name: "Collection settings" })).toHaveFocus();
  });

  it("saves a collection only once it names a group", async () => {
    mockPage();
    await createPage();
    await onlyLibrary(screen, "Movies");
    await fireEvent.input(screen.getByLabelText("Title"), { target: { value: "Draft" } });
    const save = screen.getByRole("button", { name: "Save" });
    expect(save).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Choose a group");
    await fireEvent.input(screen.getByRole("combobox", { name: "Group" }), {
      target: { value: "Brand new" },
    });
    expect(save).toBeEnabled();
  });

  it("saves a new collection on Enter, without opening Sync", async () => {
    const { calls } = mockPage();
    await createPage();
    await onlyLibrary(screen, "Movies");
    await fireEvent.input(screen.getByLabelText("Title"), { target: { value: "Draft" } });
    await fireEvent.input(screen.getByRole("combobox", { name: "Group" }), {
      target: { value: "Films" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Condition" }));
    await fireEvent.submit(screen.getByRole("form", { name: "Configure collection" }));
    await waitFor(() =>
      expect(
        calls.some(
          (call) => call.init.method === "POST" && call.url.split("?")[0] === "/api/collections",
        ),
      ).toBe(true),
    );
    expect(uiState.openPopup).toBeNull();
  });

  it("creates a smart collection combining a Radarr tag with an unplayed condition", async () => {
    const { calls } = mockPage({ "/api/collections/tags/radarr": [] });
    await createPage();
    await onlyLibrary(screen, "Movies");
    await fireEvent.input(screen.getByLabelText("Title"), { target: { value: "Requests" } });
    await fireEvent.click(screen.getByLabelText("Smart"));
    await fireEvent.click(screen.getByRole("button", { name: "Condition" }));
    await chooseOption(screen.getByLabelText("Criteria condition 1 field"), "Radarr tags");
    await fireEvent.change(screen.getByLabelText("Criteria condition 1 tags"), {
      target: { value: "request" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Condition" }));
    await chooseOption(screen.getByLabelText("Criteria condition 2 field"), "Unplayed");
    await chooseOption(screen.getByLabelText("Criteria condition 2 value"), "false");
    await fireEvent.input(screen.getByRole("combobox", { name: "Group" }), {
      target: { value: "Films" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Save and Sync" }));
    await waitFor(() =>
      expect(
        calls.some(
          (call) => call.init.method === "POST" && call.url.split("?")[0] === "/api/collections",
        ),
      ).toBe(true),
    );
    expect(postedBody(calls, "/api/collections").rule).toMatchObject({
      smart: true,
      libraries: [
        {
          criteria: {
            mode: "all",
            conditions: [
              { kind: "source", operator: "is", source: { type: "radarr_tag", tags: ["request"] } },
              { kind: "field", field: "unplayed", operator: "is", value: false },
            ],
          },
        },
      ],
    });
  });

  it("creates a set split by a dimension into a group that keeps its other defaults", async () => {
    const { calls } = mockPage({
      "/api/collection-groups/Decades": ({ init }: { init: RequestInit }) =>
        Response.json(
          init.method === "PUT" ? JSON.parse(String(init.body)) : { visible_home: true },
        ),
      "/api/collections/sets/preview": [
        {
          value: "1990",
          title: "1990s",
          member_count: 2,
          below_minimum: false,
          collection_id: null,
        },
      ],
    });
    await createPage();
    const setup = within(screen.getByRole("region", { name: "Collection setup" }));
    await onlyLibrary(setup, "Other movies");
    await fireEvent.click(setup.getByLabelText("One per value"));
    // Split by fills in the group, the title and the defaults its collections start with.
    await chooseOption(setup.getByLabelText("Split by"), "TMDB franchises");
    const group = setup.getByRole("combobox", { name: /^Group/ });
    expect(group).toHaveValue("TMDB franchises");
    await chooseOption(setup.getByLabelText("Split by"), "Decades");
    expect(group).toHaveValue("Decades");
    const set = within(screen.getByRole("region", { name: "Collection content" }));
    expect(set.queryByLabelText("Split by")).toBeNull();
    await fireEvent.click(set.getByRole("button", { name: "Preview collections" }));
    expect(await set.findByText("1990s")).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Save and Sync" }));

    await waitFor(() => expect(sidebarGroup()).toBe("Decades"));
    expect(postedBody(calls, "/api/collection-groups/Decades")).toMatchObject({
      visible_home: true,
      generator: {
        dimension: "decade",
        library_ids: ["other"],
        title_format: "{value}s",
        strip_prefix: "",
      },
    });
    expect(
      calls.some((call) => call.init.method === "PUT" && call.url.includes("new_set=true")),
    ).toBe(true);
    await waitFor(() => expect(uiState.openPopup).toBe("operations"));
    expect(syncSelection.groups).toEqual(["Decades"]);
    uiState.closePopup();
  });

  it("refuses a group that already is a set, and warns of another set splitting alike", async () => {
    mockPage({
      "/api/collection-groups": [
        { name: "Decades", set: { dimension: "decade", library_ids: ["other"] } },
        { name: "Genres", set: { dimension: "genre", library_ids: ["other"] } },
      ],
    });
    await createPage();
    const setup = within(screen.getByRole("region", { name: "Collection setup" }));
    await onlyLibrary(setup, "Other movies");
    await fireEvent.click(setup.getByLabelText("One per value"));
    await chooseOption(setup.getByLabelText("Split by"), "Decades");

    expect(await setup.findByText('"Decades" already is a set')).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save and Sync" })).toBeDisabled();

    await fireEvent.input(setup.getByRole("combobox", { name: /^Group/ }), {
      target: { value: "Film decades" },
    });
    expect(await setup.findByText('"Decades" already splits by decades')).toBeInTheDocument();
    expect(setup.queryByText(/"Genres" already splits/)).toBeNull();
    expect(screen.getByRole("button", { name: "Save and Sync" })).toBeEnabled();
  });

  it("offers an unmanaged collection only adoption, with the group it joins", async () => {
    const imported = { ...detail, kind: "smart" as const, managed: false, rule: null };
    const { calls } = mockPage({
      "/api/collections/12": imported,
      "/api/collections/12/adopt": { ...detail, collection_group: "Franchises" },
    });
    settingsState.load(
      appSettings({
        media_servers: mediaServers("plex"),
        collections_supported: true,
      }),
    );
    goToCollectionView(imported, "configure");
    renderWithQueryClient(CollectionPage);
    const adopt = await screen.findByRole("button", { name: "Adopt" });
    // Every collection Overture manages joins a group.
    expect(adopt).toBeDisabled();
    for (const name of ["Collection setup", "Collection content", "Collection settings"])
      expect(screen.queryByRole("region", { name })).toBeNull();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete collection" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Orphan collection" })).toBeNull();
    expect(screen.queryByRole("tab", { name: /Art/ })).toBeNull();

    await chooseOption(screen.getByLabelText("Group"), "Franchises");
    expect(adopt).toBeEnabled();
    await fireEvent.click(adopt);
    await waitFor(() =>
      expect(postedBody(calls, "/api/collections/12/adopt")).toEqual({
        group: "Franchises",
      }),
    );
  });

  it.each(["jellyfin", "emby"] as const)(
    "offers %s only the evaluation, fields and orders it supports",
    async (server) => {
      settingsState.load(
        appSettings({ media_servers: mediaServers(server), collections_supported: true }),
      );
      mockPage({
        "/api/collections/capabilities": collectionCapabilities({
          server_types: [server],
          smart: false,
          visibility: false,
          orders: ["release.asc", "title.asc"],
          smart_orders: [],
          fields: collectionCapabilities().fields.filter((field) => field.field !== "unplayed"),
        }),
      });
      await createPage();
      await screen.findByRole("button", { name: "Condition" });
      expect(screen.queryByRole("radiogroup", { name: "Collection type" })).toBeNull();
      await fireEvent.click(screen.getByRole("button", { name: "Condition" }));
      const field = screen.getByLabelText("Criteria condition 1 field");
      await fireEvent.click(field);
      expect(screen.queryByRole("option", { name: "Unplayed" })).toBeNull();
      expect(screen.queryByRole("option", { name: "HDR" })).toBeNull();
      await fireEvent.keyDown(field, { key: "Escape" });
      await fireEvent.click(screen.getByRole("button", { name: "Settings" }));
      const sort = within(
        screen.getByRole("region", { name: "Collection settings" }),
      ).getByLabelText("Sort");
      await fireEvent.click(sort);
      expect(
        within(screen.getByRole("listbox"))
          .getAllByRole("option")
          .map((option) => option.textContent),
      ).toEqual(["Default", "Release date (oldest first)", "Title (A to Z)"]);
      expect(screen.queryByLabelText("Collection mode")).toBeNull();
    },
  );

  it("gives each library its own criteria, in one collection", async () => {
    const { calls } = mockPage();
    await createPage();
    await fireEvent.click(screen.getByRole("checkbox", { name: "Other movies" }));
    expect(screen.getByText(/each gets its own, kept alike/)).toBeInTheDocument();
    await fireEvent.input(screen.getByLabelText("Title"), { target: { value: "Attenborough" } });
    await fireEvent.input(screen.getByRole("combobox", { name: "Group" }), {
      target: { value: "Films" },
    });
    const boxes = screen.getAllByRole("button", { name: "Condition" });
    await fireEvent.click(boxes[1] as HTMLElement);
    await chooseOption(screen.getByLabelText("Other movies criteria condition 1 field"), "Year");
    await fireEvent.input(screen.getByLabelText("Other movies criteria condition 1 value"), {
      target: { value: "1990" },
    });
    await fireEvent.click(boxes[0] as HTMLElement);
    await chooseOption(screen.getByLabelText("Movies criteria condition 1 field"), "Year");
    await fireEvent.input(screen.getByLabelText("Movies criteria condition 1 value"), {
      target: { value: "2000" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(route.pathname).toBe("/collections/12-saga"));
    const { rule } = postedBody(calls, "/api/collections?to_server=false");
    expect(rule.libraries).toMatchObject([
      { library_id: "movies", criteria: { conditions: [{ value: 2000 }] } },
      { library_id: "other", criteria: { conditions: [{ value: 1990 }] } },
    ]);
  });

  it("says one collection holds every library where the server allows it", async () => {
    mockPage({
      "/api/collections/capabilities": collectionCapabilities({ spans_libraries: true }),
    });
    await createPage();
    await fireEvent.click(screen.getByRole("checkbox", { name: "Other movies" }));
    expect(
      await screen.findByText("One collection on the server holds them all."),
    ).toBeInTheDocument();
  });

  it("suggests the kind the criteria suit as they are edited, and switches to it", async () => {
    mockPage({
      "/api/collections/recommend-kind": {
        kind: "smart",
        reason: "Plex filters every condition natively.",
      },
    });
    await createPage();
    await onlyLibrary(screen, "Movies");
    await fireEvent.click(screen.getByRole("button", { name: "Condition" }));
    await chooseOption(screen.getByLabelText("Criteria condition 1 field"), "Year");

    // No preview is needed: the advice follows the criteria.
    const title = await screen.findByText("A smart collection suits these criteria");
    const suggestion = title.closest<HTMLElement>('[role="status"]')!;
    expect(suggestion).toHaveTextContent("Plex filters every condition natively.");
    await fireEvent.click(within(suggestion).getByRole("button", { name: "Switch to smart" }));
    expect(screen.getByLabelText("Smart")).toBeChecked();
    expect(screen.queryByText("A smart collection suits these criteria")).toBeNull();
  });

  it("previews members", async () => {
    const { calls } = mockPage({
      "/api/collections/preview": {
        libraries: [{ library_id: "movies", member_count: 2, members: ["First", "Second"] }],
      },
    });
    await createPage();
    await onlyLibrary(screen, "Movies");
    await fireEvent.input(screen.getByLabelText("Title"), { target: { value: "Nineties" } });
    await fireEvent.click(screen.getByRole("button", { name: "Condition" }));
    await chooseOption(screen.getByLabelText("Criteria condition 1 field"), "Year");
    await fireEvent.click(screen.getByRole("button", { name: "Preview members" }));
    expect(await screen.findByText("2 members: First, Second")).toBeInTheDocument();
    expect(postedBody(calls, "/api/collections/preview")).toMatchObject({
      rule: { libraries: [{ library_id: "movies" }] },
    });
  });

  it("opens with only Setup and Content expanded, however it was left", async () => {
    mockPage();
    await createPage();
    const expanded = () =>
      screen
        .getAllByRole("button", { expanded: true })
        .map(
          (button) =>
            document.getElementById(button.getAttribute("aria-labelledby") ?? "")?.textContent,
        );
    expect(expanded()).toEqual(["Setup", "Content"]);

    await fireEvent.click(screen.getByRole("button", { name: "Settings", expanded: false }));
    expect(expanded()).toEqual(["Setup", "Content", "Settings"]);

    cleanup();
    renderWithQueryClient(CollectionPage);
    await screen.findByRole("checkbox", { name: "Movies" });
    expect(expanded()).toEqual(["Setup", "Content"]);
  });
});
