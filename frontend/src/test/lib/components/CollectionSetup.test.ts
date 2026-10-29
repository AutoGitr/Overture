import { fireEvent, screen, waitFor, within } from "@testing-library/svelte";
import { beforeEach, describe, expect, it } from "vitest";
import type { CollectionPresetRead } from "../../../generated/rest/types.gen";
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
} from "../../helpers/fixtures";
import { renderWithQueryClient } from "../../helpers/render";

const member = mediaItem({ id: 1, title: "First", library_id: "movies", server_item_id: "m1" });
const detail = collectionDetail({ id: 12, title: "Saga", library_id: "movies", members: [member] });
const libraries = [
  { id: "movies", title: "Movies", count: 1 },
  { id: "other", title: "Other movies", count: 1 },
];
const presets: CollectionPresetRead[] = [
  {
    key: "decades",
    label: "Decades",
    description: "One collection per decade.",
    collection: null,
    set: {
      group: "Decades",
      policy: {
        sync_mode: null,
        minimum_items: 2,
        delete_below_minimum: null,
        auto_match_art: null,
        auto_match_theme: null,
        delete_when_inactive: null,
        collection_mode: null,
        order_type: null,
        collection_filtering: null,
        visible_home: null,
        visible_shared: null,
        visible_library: null,
        sort_title_format: null,
        summary_format: null,
        active_start_mmdd: null,
        active_end_mmdd: null,
        request_missing: null,
        member_label: null,
        arr_tag: null,
        home_order: null,
      },
      generator: {
        dimension: "decade",
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
      },
    },
    saved_id: null,
  },
  {
    key: "unplayed",
    label: "Unplayed",
    description: "What each user has not played yet, newest additions first.",
    set: null,
    collection: {
      title: "Unplayed",
      collection_filtering: "user",
      rule: {
        ...collectionRule(),
        criteria: {
          mode: "all",
          conditions: [{ kind: "field", field: "unplayed", operator: "is", value: true }],
          groups: [],
        },
        smart: true,
        order_type: "release.desc",
      },
    },
    saved_id: null,
  },
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
    "/api/collections/capabilities": collectionCapabilities(),
    "/api/collections/presets": presets,
    "/api/collections/12": detail,
    "/api/collections": detail,
    "/api/collections/12/rule": collectionRule(),
    ...overrides,
  });
}

async function createPage() {
  await navigate("/movies/collections/new");
  renderWithQueryClient(CollectionPage);
  await screen.findByRole("checkbox", { name: "Movies" });
}

function postedBody(calls: { url: string; init: RequestInit }[], path: string) {
  const call = calls.find((entry) => entry.url.startsWith(path) && entry.init.method !== "GET");
  return JSON.parse(String(call?.init.body));
}

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
    settingsState.load(appSettings({ media_server: "plex", collections_supported: true }));
  });

  it("adapts Setup to a collection or a set, with no tab rows while new", async () => {
    mockPage();
    await createPage();
    const setup = within(screen.getByRole("region", { name: "Collection setup" }));
    expect(setup.getByRole("group", { name: "Libraries" })).toBeInTheDocument();
    for (const name of [/^Start from/, "Title", "Group"]) {
      expect(setup.getByLabelText(name)).toBeInTheDocument();
    }
    expect(setup.queryByLabelText("TMDB collection ID")).toBeNull();
    expect(screen.queryByRole("tablist", { name: "Detail modes" })).toBeNull();
    expect(screen.queryByRole("navigation", { name: "Configure sections" })).toBeNull();

    // Presets of both kinds share one list, grouped by what they create.
    const start = setup.getByLabelText(/^Start from/);
    expect(
      within(start)
        .getAllByRole("group")
        .map((group) => [
          group.getAttribute("label"),
          within(group)
            .getAllByRole("option")
            .map((option) => option.textContent),
        ]),
    ).toEqual([
      ["One collection", ["Unplayed"]],
      ["One collection per value", ["Decades"]],
    ]);

    await fireEvent.click(setup.getByLabelText("One per value"));
    expect(setup.queryByLabelText("Title")).toBeNull();
    expect(setup.getByRole("combobox", { name: /^Group/ })).not.toBeRequired();
    // Both kinds share their sections; a set's Title is a template.
    for (const name of ["Collection content", "Collection settings", "Collection schedule"])
      expect(screen.getByRole("region", { name })).toBeInTheDocument();
    expect(setup.getByLabelText(/^Title template/)).toHaveValue("{value}s");
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

  it("saves a new collection without the server on Enter", async () => {
    const { calls } = mockPage();
    await createPage();
    await onlyLibrary(screen, "Movies");
    await fireEvent.input(screen.getByLabelText("Title"), { target: { value: "Draft" } });
    await fireEvent.click(screen.getByRole("button", { name: "Condition" }));
    await fireEvent.submit(screen.getByRole("form", { name: "Configure collection" }));
    await waitFor(() => expect(calls.some((call) => call.init.method === "POST")).toBe(true));
    expect(
      calls
        .find((call) => call.init.method === "POST")
        ?.url.startsWith("/api/collections?to_server=false"),
    ).toBe(true);
  });

  it("creates a per-user smart collection from a preset", async () => {
    const { calls } = mockPage();
    await createPage();
    await onlyLibrary(screen, "Movies");
    await fireEvent.change(screen.getByLabelText(/^Start from/), { target: { value: "unplayed" } });
    expect(screen.getByText(presets[1]?.description ?? "")).toBeInTheDocument();
    expect(screen.getByLabelText("Title")).toHaveValue("Unplayed");
    expect(screen.getByLabelText("Plex (smart)")).toBeChecked();
    expect(screen.getByLabelText("Criteria condition 1 field")).toHaveValue("field:unplayed");
    await fireEvent.click(screen.getByRole("button", { name: "Save and Create" }));
    await waitFor(() => expect(route.pathname).toBe("/movies/collections/12-saga"));
    expect(postedBody(calls, "/api/collections")).toMatchObject({
      title: "Unplayed",
      library_id: "movies",
      collection_filtering: "user",
      order_type: "release.desc",
      rule: {
        smart: true,
        order_type: "release.desc",
        criteria: {
          conditions: [{ kind: "field", field: "unplayed", operator: "is", value: true }],
        },
      },
    });
  });

  it("creates a smart collection combining a Radarr tag with an unplayed condition", async () => {
    const { calls } = mockPage({ "/api/collections/tags/radarr": [] });
    await createPage();
    await onlyLibrary(screen, "Movies");
    await fireEvent.input(screen.getByLabelText("Title"), { target: { value: "Requests" } });
    await fireEvent.click(screen.getByLabelText("Plex (smart)"));
    await fireEvent.click(screen.getByRole("button", { name: "Condition" }));
    await fireEvent.change(screen.getByLabelText("Criteria condition 1 field"), {
      target: { value: "source:radarr_tag" },
    });
    await fireEvent.change(screen.getByLabelText("Criteria condition 1 tags"), {
      target: { value: "request" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Condition" }));
    await fireEvent.change(screen.getByLabelText("Criteria condition 2 field"), {
      target: { value: "field:unplayed" },
    });
    await fireEvent.change(screen.getByLabelText("Criteria condition 2 value"), {
      target: { value: "false" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Save and Create" }));
    await waitFor(() => expect(calls.some((call) => call.init.method === "POST")).toBe(true));
    expect(postedBody(calls, "/api/collections").rule).toMatchObject({
      smart: true,
      criteria: {
        mode: "all",
        conditions: [
          { kind: "source", operator: "is", source: { type: "radarr_tag", tags: ["request"] } },
          { kind: "field", field: "unplayed", operator: "is", value: false },
        ],
      },
    });
  });

  it("creates a collection set from a preset into a group that keeps its other defaults", async () => {
    const { calls } = mockPage({
      "/api/collections/group-policy": ({ init }: { init: RequestInit }) =>
        Response.json(
          init.method === "PUT" ? JSON.parse(String(init.body)) : { visible_home: true },
        ),
      "/api/collections/group-policy/sync": {
        created: [12, 13],
        removed: [],
        synced: 0,
        errors: {},
      },
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
    // Choosing a set preset switches the form to a set.
    await fireEvent.change(setup.getByLabelText(/^Start from/), { target: { value: "decades" } });
    expect(setup.getByLabelText("One per value")).toBeChecked();
    expect(setup.getByRole("combobox", { name: /^Group/ })).toHaveValue("Decades");
    const set = within(screen.getByRole("region", { name: "Collection content" }));
    expect(set.getByLabelText("Split by")).toHaveValue("decade");
    await fireEvent.click(set.getByRole("button", { name: "Preview collections" }));
    expect(await set.findByText("1990s")).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Save and Create" }));

    await waitFor(() => expect(sidebarGroup()).toBe("Decades"));
    expect(postedBody(calls, "/api/collections/group-policy?")).toMatchObject({
      visible_home: true,
      minimum_items: 2,
      generator: { dimension: "decade", library_ids: ["other"], title_format: "{value}s" },
    });
    expect(calls.some((call) => call.url.startsWith("/api/collections/group-policy/sync"))).toBe(
      true,
    );
  });

  it("offers an unmanaged collection only a take-over, with the group it joins", async () => {
    const imported = { ...detail, kind: "smart" as const, managed: false, rule: null };
    const { calls } = mockPage({
      "/api/collections/12": imported,
      "/api/collections/12/take-over": { ...detail, collection_group: "Franchises" },
    });
    settingsState.load(
      appSettings({
        media_server: "plex",
        collections_supported: true,
        collection_require_group: true,
      }),
    );
    goToCollectionView(imported, "configure");
    renderWithQueryClient(CollectionPage);
    const takeOver = await screen.findByRole("button", { name: "Take over" });
    expect(takeOver).toBeDisabled();
    for (const name of ["Collection setup", "Collection content", "Collection settings"])
      expect(screen.queryByRole("region", { name })).toBeNull();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete collection" })).toBeNull();
    expect(screen.queryByRole("tab", { name: /Art/ })).toBeNull();

    await screen.findByRole("option", { name: "Franchises" });
    await fireEvent.change(screen.getByLabelText("Group"), { target: { value: "Franchises" } });
    expect(takeOver).toBeEnabled();
    await fireEvent.click(takeOver);
    await waitFor(() =>
      expect(postedBody(calls, "/api/collections/12/take-over")).toEqual({
        group: "Franchises",
      }),
    );
  });

  it.each(["jellyfin", "emby"] as const)(
    "offers %s only the evaluation, fields and orders it supports",
    async (server) => {
      settingsState.load(appSettings({ media_server: server, collections_supported: true }));
      mockPage({
        "/api/collections/capabilities": collectionCapabilities({
          server_type: server,
          smart: false,
          visibility: false,
          orders: ["release.asc", "title.asc"],
          smart_orders: [],
          fields: collectionCapabilities().fields.filter((field) => field.field !== "unplayed"),
        }),
      });
      await createPage();
      await screen.findByRole("button", { name: "Condition" });
      expect(screen.queryByRole("radiogroup", { name: "Evaluated by" })).toBeNull();
      await fireEvent.click(screen.getByRole("button", { name: "Condition" }));
      const field = screen.getByLabelText("Criteria condition 1 field");
      expect(within(field).queryByRole("option", { name: "Unplayed" })).toBeNull();
      expect(within(field).queryByRole("option", { name: "HDR" })).toBeNull();
      await fireEvent.click(screen.getByRole("button", { name: "Settings" }));
      expect(
        within(
          within(screen.getByRole("region", { name: "Collection settings" })).getByLabelText(
            "Sort",
          ),
        )
          .getAllByRole("option")
          .map((option) => option.textContent),
      ).toEqual(["Default", "Release date (oldest first)", "Title (A to Z)"]);
      expect(screen.queryByLabelText("Collection mode")).toBeNull();
    },
  );

  it("keeps one collection alike in several libraries as a set, saved in Overture only", async () => {
    const { calls } = mockPage({
      "/api/collections/group-policy": ({ init }: { init: RequestInit }) =>
        Response.json(init.method === "PUT" ? JSON.parse(String(init.body)) : {}),
    });
    await createPage();
    for (const name of ["Movies", "Other movies"]) {
      const box = screen.getByRole("checkbox", { name });
      if (!(box instanceof HTMLInputElement) || !box.checked) await fireEvent.click(box);
    }
    expect(screen.getByText(/Several libraries make a set/)).toBeInTheDocument();
    await fireEvent.input(screen.getByLabelText("Title"), { target: { value: "Attenborough" } });
    await fireEvent.click(screen.getByRole("button", { name: "Condition" }));
    await fireEvent.change(screen.getByLabelText("Criteria condition 1 field"), {
      target: { value: "field:year" },
    });
    await fireEvent.input(screen.getByLabelText("Criteria condition 1 value"), {
      target: { value: "1990" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(sidebarGroup()).toBe("Attenborough"));
    expect(postedBody(calls, "/api/collections/group-policy?")).toMatchObject({
      generator: {
        dimension: "custom",
        library_ids: ["movies", "other"],
        custom_values: [{ name: "Attenborough" }],
      },
    });
    expect(calls.some((call) => call.url.startsWith("/api/collections/group-policy/sync"))).toBe(
      false,
    );
  });

  it("suggests the collection kind the preview recommends, and switches to it", async () => {
    mockPage({
      "/api/collections/preview": {
        member_count: 2,
        members: ["First", "Second"],
        recommendation: { kind: "smart", reason: "Plex keeps it current without syncs" },
      },
      "/api/collections/presets": presets,
    });
    await createPage();
    await onlyLibrary(screen, "Movies");
    await fireEvent.click(screen.getByRole("button", { name: "Condition" }));
    await fireEvent.change(screen.getByLabelText("Criteria condition 1 field"), {
      target: { value: "field:year" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Preview members" }));

    const hint = await screen.findByRole("note");
    expect(hint).toHaveTextContent("A smart collection suits these criteria");
    await fireEvent.click(within(hint).getByRole("button", { name: "Switch" }));
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });

  it("previews members and saves the form as a preset", async () => {
    let preset: unknown = null;
    const { calls } = mockPage({
      "/api/collections/preview": { member_count: 2, members: ["First", "Second"] },
      "/api/collections/presets": ({ init }: { init: RequestInit }) => {
        if (init.method !== "POST") return Response.json(presets);
        preset = JSON.parse(String(init.body));
        return Response.json({ ...presets[1], key: "saved:1", label: "Mine", saved_id: 1 });
      },
    });
    await createPage();
    await onlyLibrary(screen, "Movies");
    await fireEvent.input(screen.getByLabelText("Title"), { target: { value: "Nineties" } });
    await fireEvent.click(screen.getByRole("button", { name: "Condition" }));
    await fireEvent.change(screen.getByLabelText("Criteria condition 1 field"), {
      target: { value: "field:year" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Preview members" }));
    expect(await screen.findByText("2 members: First, Second")).toBeInTheDocument();
    expect(postedBody(calls, "/api/collections/preview")).toMatchObject({
      library_id: "movies",
      media_type: "movie",
    });

    await fireEvent.input(screen.getByLabelText("Save as preset"), { target: { value: "Mine" } });
    await fireEvent.click(screen.getByRole("button", { name: "Save preset" }));
    await waitFor(() =>
      expect(preset).toMatchObject({
        label: "Mine",
        collection: { title: "Nineties", rule: { criteria: { conditions: [{ field: "year" }] } } },
      }),
    );
  });
});
