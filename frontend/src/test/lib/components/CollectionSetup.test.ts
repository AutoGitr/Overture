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
        enabled: true,
      },
    },
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
  await screen.findByRole("option", { name: "Movies" });
}

function postedBody(calls: { url: string; init: RequestInit }[], path: string) {
  const call = calls.find((entry) => entry.url.startsWith(path) && entry.init.method !== "GET");
  return JSON.parse(String(call?.init.body));
}

describe("collection setup flow", () => {
  beforeEach(() => {
    queryClient.clear();
    settingsState.load(appSettings({ media_server: "plex", collections_supported: true }));
  });

  it("adapts Setup and the section shortcuts to a collection or a set", async () => {
    mockPage();
    await createPage();
    const setup = within(screen.getByRole("region", { name: "Collection setup" }));
    for (const name of ["Library", /^Start from/, "Title", "Group"]) {
      expect(setup.getByLabelText(name)).toBeInTheDocument();
    }
    expect(setup.queryByLabelText("TMDB collection ID")).toBeNull();
    expect(screen.queryByRole("link", { name: "Members" })).toBeNull();
    for (const name of ["Setup", "Content", "Display", "Schedule"]) {
      const target = screen.getByRole("link", { name }).getAttribute("href")?.slice(1);
      expect(document.getElementById(target ?? "")).not.toBeNull();
    }

    await fireEvent.click(setup.getByLabelText("Collection set"));
    expect(setup.queryByLabelText("Title")).toBeNull();
    expect(setup.getByRole("combobox", { name: /^Group/ })).toBeRequired();
    expect(
      within(setup.getByLabelText(/^Start from/))
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["Choose a set", "Decades"]);
    expect(screen.getAllByRole("link").map((link) => link.textContent?.trim())).toEqual(
      expect.arrayContaining(["Setup", "Collections", "Defaults"]),
    );
    expect(screen.queryByRole("link", { name: "Schedule" })).toBeNull();
  });

  it("starts with only Setup and Content expanded and opens sections through navigation", async () => {
    mockPage();
    await createPage();
    for (const name of ["Setup", "Content"])
      expect(screen.getByRole("button", { name })).toHaveAttribute("aria-expanded", "true");
    const display = screen.getByRole("button", { name: "Display" });
    expect(display).toHaveAttribute("aria-expanded", "false");
    await fireEvent.click(screen.getByRole("link", { name: "Display" }));
    expect(display).toHaveAttribute("aria-expanded", "true");
  });

  it("creates a per-user smart collection from a preset", async () => {
    const { calls } = mockPage();
    await createPage();
    await fireEvent.change(screen.getByLabelText("Library"), { target: { value: "movies" } });
    await fireEvent.change(screen.getByLabelText(/^Start from/), { target: { value: "unplayed" } });
    expect(screen.getByText(presets[1]?.description ?? "")).toBeInTheDocument();
    expect(screen.getByLabelText("Title")).toHaveValue("Unplayed");
    expect(screen.getByLabelText("Plex smart collection")).toBeChecked();
    expect(screen.getByLabelText("Criteria condition 1 field")).toHaveValue("field:unplayed");
    await fireEvent.click(screen.getByRole("button", { name: "Create collection" }));
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
    await fireEvent.change(screen.getByLabelText("Library"), { target: { value: "movies" } });
    await fireEvent.input(screen.getByLabelText("Title"), { target: { value: "Requests" } });
    await fireEvent.click(screen.getByLabelText("Plex smart collection"));
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
    await fireEvent.click(screen.getByRole("button", { name: "Create collection" }));
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
    await fireEvent.change(setup.getByLabelText("Library"), { target: { value: "other" } });
    await fireEvent.click(setup.getByLabelText("Collection set"));
    await fireEvent.change(setup.getByLabelText(/^Start from/), { target: { value: "decades" } });
    expect(setup.getByRole("combobox", { name: /^Group/ })).toHaveValue("Decades");
    const set = within(screen.getByRole("region", { name: "Set collections" }));
    expect(set.getByLabelText("One collection per")).toHaveValue("decade");
    await fireEvent.click(set.getByRole("button", { name: "Preview collections" }));
    expect(await set.findByText("1990s")).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Create set" }));

    await waitFor(() => expect(sidebarGroup()).toBe("Decades"));
    expect(postedBody(calls, "/api/collections/group-policy?")).toMatchObject({
      visible_home: true,
      minimum_items: 2,
      generator: { dimension: "decade", library_id: "other", title_format: "{value}s" },
    });
    expect(calls.some((call) => call.url.startsWith("/api/collections/group-policy/sync"))).toBe(
      true,
    );
  });

  it("keeps an imported Plex filter until Overture is told to replace it", async () => {
    const smart = { ...detail, kind: "smart" as const, rule: null };
    const { calls } = mockPage({
      "/api/collections/12": ({ init }: { init: RequestInit }) =>
        Response.json(
          init.method === "PUT" ? { ...smart, ...JSON.parse(String(init.body)) } : smart,
        ),
    });
    goToCollectionView(smart, "configure");
    renderWithQueryClient(CollectionPage);
    const replace = await screen.findByLabelText("Replace the Plex filter with these criteria");
    expect(replace).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Condition" })).toBeDisabled();
    expect(screen.queryByLabelText("Add item")).toBeNull();
    expect(screen.queryByRole("button", { name: "Remove First from collection" })).toBeNull();

    await fireEvent.input(screen.getByLabelText("Title"), {
      target: { value: "Renamed smart collection" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Save Changes" }));
    await waitFor(() => expect(calls.some((call) => call.init.method === "PUT")).toBe(true));
    expect(calls.some((call) => call.url.includes("/rule"))).toBe(false);

    await waitFor(() => expect(screen.getByRole("button", { name: "Save Changes" })).toBeEnabled());
    await fireEvent.click(replace);
    await fireEvent.click(screen.getByRole("button", { name: "Condition" }));
    await fireEvent.input(screen.getByLabelText("Criteria condition 1 value"), {
      target: { value: "Saga" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Save Changes" }));
    await waitFor(() =>
      expect(calls.some((call) => call.url.includes("/rule") && call.init.method === "PUT")).toBe(
        true,
      ),
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
      expect(screen.queryByRole("radiogroup", { name: "Evaluation" })).toBeNull();
      await fireEvent.click(screen.getByRole("button", { name: "Condition" }));
      const field = screen.getByLabelText("Criteria condition 1 field");
      expect(within(field).queryByRole("option", { name: "Unplayed" })).toBeNull();
      expect(within(field).queryByRole("option", { name: "HDR" })).toBeNull();
      expect(
        within(
          within(screen.getByRole("region", { name: "Collection content" })).getByLabelText(
            /^Sort/,
          ),
        )
          .getAllByRole("option")
          .map((option) => option.textContent),
      ).toEqual(["Default", "Release date (oldest first)", "Title (A to Z)"]);
      expect(screen.queryByLabelText("Visibility")).toBeNull();
    },
  );
});
