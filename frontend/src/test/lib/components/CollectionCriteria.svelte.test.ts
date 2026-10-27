import { fireEvent, screen, waitFor, within } from "@testing-library/svelte";
import { beforeEach, describe, expect, it } from "vitest";
import type {
  CollectionGroupPolicyOutput,
  CollectionSourceInput,
  FilterGroupInput,
} from "../../../generated/rest/types.gen";
import CollectionGroupSettings from "../../../lib/components/CollectionGroupSettings.svelte";
import CollectionPolicyFields from "../../../lib/components/CollectionPolicyFields.svelte";
import CollectionSetEditor from "../../../lib/components/CollectionSetEditor.svelte";
import GlobalCollectionDefaults from "../../../lib/components/GlobalCollectionDefaults.svelte";
import CriteriaEditor from "../../../lib/components/CriteriaEditor.svelte";
import SourceFields from "../../../lib/components/SourceFields.svelte";
import CollectionPage from "../../../lib/router/pages/CollectionPage.svelte";
import { queryClient } from "../../../lib/rest/queryClient";
import { goToCollectionView, navigate } from "../../../lib/router/routes";
import { settingsState } from "../../../lib/stores/settingsState.svelte";
import { emptyGroup } from "../../../lib/utils/collectionCriteria";
import { defaultGenerator } from "../../../lib/utils/collectionForms.svelte";
import { mockFetchRoutes } from "../../helpers/fetch";
import {
  appSettings,
  collectionCapabilities,
  collectionDetail,
  collectionRule,
  mediaItem,
} from "../../helpers/fixtures";
import { renderWithQueryClient } from "../../helpers/render";

const capabilities = collectionCapabilities();
const members = [mediaItem({ id: 1, title: "First", library_id: "movies", server_item_id: "m1" })];
const detail = collectionDetail({
  id: 12,
  title: "Saga",
  library_id: "movies",
  members,
  child_count: 1,
});
const rule = collectionRule();

describe("collection criteria", () => {
  beforeEach(async () => {
    queryClient.clear();
    settingsState.load(appSettings({ media_server: "plex", collections_supported: true }));
    await navigate("/movies/collections/:collectionSlug", {
      params: { collectionSlug: "12-saga" },
    });
  });

  it("builds field and source conditions in nested any and all groups", async () => {
    mockFetchRoutes({
      "/api/collections/field-values": [{ value: "Action", count: 3 }],
    });
    const group = $state<FilterGroupInput>(emptyGroup());
    renderWithQueryClient(CriteriaEditor, {
      group,
      fields: capabilities.fields.filter((field) => field.local),
      sources: capabilities.sources,
      mediaType: "movie",
      libraryId: "movies",
      label: "Criteria",
    });

    await fireEvent.click(screen.getByRole("button", { name: "Condition" }));
    await fireEvent.change(screen.getByLabelText("Criteria condition 1 field"), {
      target: { value: "field:genre" },
    });
    const value = screen.getByLabelText("Criteria condition 1 value");
    await fireEvent.input(value, { target: { value: "Action" } });
    // Tag values are suggested from the library.
    await waitFor(() =>
      expect(document.querySelector(`#${value.getAttribute("list")} option`)).toHaveValue("Action"),
    );

    await fireEvent.click(screen.getByRole("button", { name: "Group" }));
    const nested = within(screen.getByRole("group", { name: "Criteria group 1" }));
    await fireEvent.click(nested.getByRole("button", { name: "Condition" }));
    const subject = nested.getByLabelText("Criteria group 1 condition 1 field");
    expect(within(subject).getByRole("option", { name: /Sonarr tags/ })).toBeDisabled();
    await fireEvent.change(subject, { target: { value: "source:mdblist" } });
    await fireEvent.change(nested.getByLabelText("Criteria group 1 condition 1 operator"), {
      target: { value: "is_not" },
    });
    await fireEvent.change(nested.getByLabelText("Criteria group 1 condition 1 MDBList lists"), {
      target: { value: "user/list, other/list" },
    });
    await fireEvent.click(nested.getByRole("button", { name: "Condition" }));
    await fireEvent.change(nested.getByLabelText("Criteria group 1 condition 2 field"), {
      target: { value: "field:added" },
    });
    await fireEvent.change(nested.getByLabelText("Criteria group 1 condition 2 operator"), {
      target: { value: "after" },
    });
    await fireEvent.input(nested.getByLabelText("Criteria group 1 condition 2 value"), {
      target: { value: "2020-01-31" },
    });
    await fireEvent.change(screen.getByLabelText("Criteria match"), { target: { value: "any" } });

    expect($state.snapshot(group)).toEqual({
      mode: "any",
      conditions: [{ kind: "field", field: "genre", operator: "is", value: "Action" }],
      groups: [
        {
          mode: "any",
          conditions: [
            {
              kind: "source",
              operator: "is_not",
              source: { type: "mdblist", identifiers: ["user/list", "other/list"] },
            },
            { kind: "field", field: "added", operator: "after", value: "2020-01-31" },
          ],
          groups: [],
        },
      ],
    });

    await fireEvent.click(screen.getByRole("button", { name: "Remove Criteria group 1" }));
    await fireEvent.click(screen.getByRole("button", { name: "Remove Criteria condition 1" }));
    expect($state.snapshot(group)).toEqual({ mode: "any", conditions: [], groups: [] });
    expect(screen.getByText("No conditions yet.")).toBeInTheDocument();
  });

  it("edits person credits and offers the configured Radarr tags", async () => {
    mockFetchRoutes({ "/api/collections/tags/radarr": [{ id: 1, label: "criterion" }] });
    const person = $state<CollectionSourceInput>({
      type: "tmdb_person",
      person_id: 0,
      roles: ["actor"],
    });
    const tags = $state<CollectionSourceInput>({ type: "radarr_tag", tags: [] });
    renderWithQueryClient(SourceFields, { source: person, mediaType: "movie", label: "Person" });
    renderWithQueryClient(SourceFields, { source: tags, mediaType: "movie", label: "Tags" });

    await fireEvent.input(screen.getByLabelText("Person TMDB person ID"), {
      target: { value: "525" },
    });
    const credits = within(screen.getByRole("group", { name: "Person credits" }));
    await fireEvent.click(credits.getByLabelText("Director"));
    await fireEvent.click(credits.getByLabelText("Actor"));
    expect($state.snapshot(person)).toEqual({
      type: "tmdb_person",
      person_id: 525,
      roles: ["director"],
    });

    await fireEvent.click(await screen.findByRole("button", { name: "criterion" }));
    expect($state.snapshot(tags)).toEqual({ type: "radarr_tag", tags: ["criterion"] });
    expect(screen.getByRole("button", { name: "criterion" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("picks people and franchises from a TMDB search", async () => {
    mockFetchRoutes({
      "/api/tmdb/people/search": {
        results: [
          {
            tmdb_id: 525,
            name: "Christopher Nolan",
            known_for_department: "Directing",
            profile_url: null,
            profile_preview_url: null,
          },
        ],
      },
      "/api/tmdb/search": {
        results: [
          {
            kind: "collection",
            tmdb_id: 10,
            title: "Star Wars Collection",
            poster_url: null,
            poster_preview_url: null,
          },
        ],
      },
    });
    const person = $state<CollectionSourceInput>({ type: "tmdb_person", person_id: 0 });
    const franchise = $state<CollectionSourceInput>({ type: "tmdb_collection", collection_id: 0 });
    renderWithQueryClient(SourceFields, { source: person, mediaType: "movie", label: "Person" });
    renderWithQueryClient(SourceFields, { source: franchise, mediaType: "movie", label: "Saga" });

    await fireEvent.input(screen.getByLabelText("Person person search"), {
      target: { value: "Nolan" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Search Person person" }));
    await fireEvent.click(await screen.findByRole("button", { name: /Christopher Nolan/ }));
    expect($state.snapshot(person)).toMatchObject({
      person_id: 525,
      person_name: "Christopher Nolan",
    });

    await fireEvent.input(screen.getByLabelText("Saga franchise search"), {
      target: { value: "Star Wars" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Search Saga franchise" }));
    await fireEvent.click(await screen.findByRole("button", { name: "Star Wars Collection" }));
    expect($state.snapshot(franchise)).toEqual({ type: "tmdb_collection", collection_id: 10 });
    expect(screen.getByLabelText("Saga TMDB franchise ID")).toHaveValue(10);
  });

  it("names inherited values and keeps member effects off the global level", () => {
    const collection = renderWithQueryClient(CollectionPolicyFields, {
      policy: { sync_mode: null },
      level: "collection",
      defaults: { sync_mode: "append" },
      arr: "Radarr",
      memberLabels: true,
    });
    expect(screen.getByRole("option", { name: "Default (Append)" })).toBeInTheDocument();
    expect(screen.getByLabelText("Member label")).toBeInTheDocument();
    expect(screen.getByLabelText("Radarr tag")).toBeInTheDocument();
    collection.unmount();

    renderWithQueryClient(CollectionPolicyFields, {
      policy: { sync_mode: "sync" },
      level: "global",
      arr: "Radarr",
      memberLabels: true,
    });
    expect(screen.queryByRole("option", { name: /^Default/ })).toBeNull();
    expect(screen.queryByLabelText("Member label")).toBeNull();
    expect(screen.queryByLabelText("Radarr tag")).toBeNull();
    expect(screen.getByLabelText("Request missing")).toBeInTheDocument();
  });

  it("offers the sorts the server supports", () => {
    renderWithQueryClient(CollectionPolicyFields, {
      policy: { order_type: null },
      level: "collection",
      orders: ["custom", "critic_rating.desc"],
    });
    expect(
      within(screen.getByLabelText("Sort"))
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["Default", "Custom (manual or source order)", "Critic rating (highest first)"]);
  });

  it("switches criteria to a Plex smart collection with Plex's fields and sorts", async () => {
    let saved: unknown = null;
    mockFetchRoutes({
      "/api/collections/defaults": {},
      "/api/collections/groups": [],
      "/api/collections/capabilities": capabilities,
      "/api/collections/12": ({ init }: { init: RequestInit }) =>
        Response.json(init.method === "PUT" ? detail : { ...detail, rule }),
      "/api/collections/12/rule": ({ init }: { init: RequestInit }) => {
        saved = JSON.parse(String(init.body));
        return Response.json(rule);
      },
    });
    goToCollectionView(detail, "configure");
    renderWithQueryClient(CollectionPage);

    const content = within(await screen.findByRole("region", { name: "Collection content" }));
    const settings = within(screen.getByRole("region", { name: "Collection settings" }));
    await fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    const field = await content.findByLabelText("Criteria condition 1 field");
    expect(within(field).queryByRole("option", { name: "HDR" })).toBeNull();
    expect(
      within(settings.getByLabelText("Sort")).getByRole("option", { name: /^Custom/ }),
    ).toBeInTheDocument();

    await fireEvent.click(content.getByLabelText("Plex (smart)"));
    expect(within(field).getByRole("option", { name: "HDR" })).toBeInTheDocument();
    expect(
      within(settings.getByLabelText("Sort")).queryByRole("option", { name: /^Custom/ }),
    ).toBeNull();
    await fireEvent.change(settings.getByLabelText("Sort"), {
      target: { value: "critic_rating.desc" },
    });
    await fireEvent.input(settings.getByLabelText(/^Limit/), { target: { value: "25" } });
    await fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(saved).not.toBeNull());
    expect(saved).toMatchObject({
      smart: true,
      limit: 25,
      order_type: "critic_rating.desc",
      criteria: rule.criteria,
    });
  });

  it("saves display, seasonal and Plex visibility choices", async () => {
    let putBody: unknown = null;
    mockFetchRoutes({
      "/api/collections/12/rule": rule,
      "/api/collections/defaults": {},
      "/api/collections/groups": [],
      "/api/collections/capabilities": capabilities,
      "/api/library/libraries": [{ id: "movies", title: "Movies", count: 1 }],
      "/api/library/items": { items: members, total: 1 },
      "/api/collections/12": ({ init }: { init: RequestInit }) => {
        if (init.method === "PUT") {
          putBody = JSON.parse(String(init.body));
          return Response.json({ ...detail, ...JSON.parse(String(init.body)) });
        }
        return Response.json({ ...detail, rule });
      },
    });
    goToCollectionView(detail, "configure");
    renderWithQueryClient(CollectionPage);

    const display = within(await screen.findByRole("region", { name: "Collection settings" }));
    await fireEvent.input(display.getByLabelText(/^Summary$/i), {
      target: { value: "{title} - {group}" },
    });
    const schedule = within(screen.getByRole("region", { name: "Collection schedule" }));
    await fireEvent.input(schedule.getByLabelText(/^Active from/i), {
      target: { value: "12-15" },
    });
    await fireEvent.input(schedule.getByLabelText(/^Active until/i), {
      target: { value: "01-05" },
    });
    await fireEvent.change(await display.findByLabelText(/Shared users' home/i), {
      target: { value: "true" },
    });
    await fireEvent.change(display.getByLabelText(/Collection filtering/i), {
      target: { value: "admin" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(putBody).not.toBeNull());
    expect(putBody).toMatchObject({
      summary_format: "{title} - {group}",
      active_start_mmdd: "12-15",
      active_end_mmdd: "01-05",
      visible_shared: true,
      collection_filtering: "admin",
    });
  });

  it("turns a group into a collection set, previews it, saves it and runs it", async () => {
    let putBody: CollectionGroupPolicyOutput | null = null;
    let synced = false;
    const groupPolicy: CollectionGroupPolicyOutput = {
      sync_mode: null,
      minimum_items: 2,
      delete_below_minimum: null,
      auto_match_art: null,
      auto_match_theme: null,
      delete_when_inactive: null,
      collection_mode: null,
      collection_filtering: null,
      visible_shared: null,
      visible_library: null,
      sort_title_format: null,
      summary_format: null,
      active_start_mmdd: null,
      active_end_mmdd: null,
      generator: null,
      sync_enabled: null,
      sync_schedule: null,
      request_missing: null,
      member_label: null,
      arr_tag: null,
      home_order: null,
      visible_home: null,
      order_type: null,
    };
    const { calls } = mockFetchRoutes({
      "/api/collections/defaults": {},
      "/api/collections/capabilities": capabilities,
      "/api/collections/sets/preview": [
        {
          value: "Action",
          title: "Action",
          member_count: 3,
          below_minimum: false,
          collection_id: null,
        },
        {
          value: "Drama",
          title: "Drama",
          member_count: 1,
          below_minimum: true,
          collection_id: null,
        },
      ],
      "/api/collections/group-policy": ({ init }: { init: RequestInit }) => {
        if (init.method === "PUT") {
          putBody = JSON.parse(String(init.body));
          return Response.json(putBody);
        }
        return Response.json(groupPolicy);
      },
      "/api/collections/group-policy/sync": () => {
        synced = true;
        return Response.json({ created: [4], removed: [], synced: 0, errors: {} });
      },
    });
    renderWithQueryClient(CollectionGroupSettings, {
      group: "Genres",
      mediaType: "movie",
      libraries: [{ id: "movies", title: "Movies", count: 10 }],
    });

    await fireEvent.click(await screen.findByRole("button", { name: "Collection set" }));
    await fireEvent.click(screen.getByLabelText("Create this group's collections"));
    await fireEvent.change(screen.getByLabelText("Split by"), {
      target: { value: "genre" },
    });
    expect(screen.getByLabelText(/^Title/)).toHaveValue("{value}");
    await fireEvent.input(screen.getByLabelText(/^Most common only/), {
      target: { value: "10" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Preview collections" }));
    expect(await screen.findByText("1 collection, 1 below the minimum.")).toBeInTheDocument();
    const preview = JSON.parse(
      String(calls.find((call) => call.url.startsWith("/api/collections/sets"))?.init.body),
    );
    expect(preview).toMatchObject({
      media_type: "movie",
      group: "Genres",
      minimum_items: 2,
      generator: { dimension: "genre", library_ids: ["movies"], top: 10 },
    });

    await fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(putBody).not.toBeNull());
    expect(synced).toBe(false);
    expect(putBody).toMatchObject({
      minimum_items: 2,
      generator: { dimension: "genre", library_ids: ["movies"], title_format: "{value}", top: 10 },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Save and Sync" }));
    await waitFor(() => expect(synced).toBe(true));
  });

  it("lists a custom set's collections and renames or merges other values", async () => {
    const generator = $state(defaultGenerator(["movies"]));
    renderWithQueryClient(CollectionSetEditor, {
      generator,
      libraryIds: ["movies"],
      libraries: [{ id: "movies", title: "Movies", count: 1 }],
      mediaType: "movie",
      capabilities: collectionCapabilities({
        dimensions: [
          ...capabilities.dimensions,
          {
            dimension: "audio_language",
            label: "Audio languages",
            title_format: "{value}",
            smart_only: true,
          },
        ],
      }),
      group: "Mine",
      minimum: null,
      titled: true,
    });
    await fireEvent.click(screen.getByRole("button", { name: "Add alias" }));
    await fireEvent.change(screen.getByLabelText("Alias 1 values"), {
      target: { value: "1990, 2000" },
    });
    await fireEvent.input(screen.getByLabelText("Alias 1 title"), {
      target: { value: "Turn of the century" },
    });
    expect($state.snapshot(generator.aliases)).toEqual([
      { values: ["1990", "2000"], name: "Turn of the century" },
    ]);
    await fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(generator.aliases).toEqual([]);

    await fireEvent.change(screen.getByLabelText("Split by"), { target: { value: "custom" } });
    expect(generator.custom_values).toHaveLength(1);
    await fireEvent.click(screen.getByRole("button", { name: "Add collection" }));
    await fireEvent.input(screen.getByLabelText("Collection 2 name"), {
      target: { value: "B" },
    });
    expect(generator.custom_values?.map((value) => value.name)).toEqual(["", "B"]);
    await fireEvent.click(screen.getAllByRole("button", { name: "Remove" })[0]!);
    expect(generator.custom_values?.map((value) => value.name)).toEqual(["B"]);

    await fireEvent.change(screen.getByLabelText("Split by"), {
      target: { value: "audio_language" },
    });
    expect(generator.smart).toBe(true);
    expect(generator.custom_values).toEqual([]);
    expect(screen.getByText("Only Plex knows these values.")).toBeInTheDocument();
    await fireEvent.click(screen.getByLabelText(/Remove collections whose value/));
    expect(generator.remove_vanished).toBe(true);
  });

  it("edits the global defaults under their own names and where requests go", async () => {
    settingsState.load(
      appSettings({
        media_server: "plex",
        collections_supported: true,
        radarr_configured: true,
        tmdb_configured: true,
      }),
    );
    mockFetchRoutes({
      "/api/collections/capabilities": capabilities,
      "/api/collections/arr-options": {
        root_folders: ["/movies"],
        quality_profiles: [{ id: 4, label: "HD" }],
      },
    });
    const draft = $state(settingsState.toUpdatePayload());
    renderWithQueryClient(GlobalCollectionDefaults, { draft });
    await fireEvent.change(screen.getByLabelText("Sync mode"), { target: { value: "append" } });
    expect(draft.collection_sync_mode).toBe("append");
    await fireEvent.input(screen.getByLabelText("Sort title"), { target: { value: "" } });
    expect(draft.collection_sort_title_format).toBe("");
    await fireEvent.change(screen.getByLabelText("Collection mode"), {
      target: { value: "hide" },
    });
    expect(draft.collection_mode_default).toBe("hide");
    await fireEvent.input(screen.getByLabelText("TMDB region"), { target: { value: "SE" } });
    expect(draft.tmdb_region).toBe("SE");
    await screen.findByRole("option", { name: "/movies" });
    await fireEvent.change(screen.getByLabelText("Radarr root folder"), {
      target: { value: "/movies" },
    });
    expect(draft.radarr_root_folder).toBe("/movies");
    expect(screen.queryByLabelText("Sonarr root folder")).toBeNull();
    expect(screen.queryByRole("option", { name: /^Default/ })).toBeNull();
  });

  it("picks a TMDB chart and how many of its titles count", async () => {
    mockFetchRoutes({ "/api/collections/capabilities": capabilities });
    const chart = $state<CollectionSourceInput>({
      type: "tmdb_chart",
      chart: "popular",
      limit: 100,
    });
    renderWithQueryClient(SourceFields, { source: chart, mediaType: "movie", label: "Chart" });
    await screen.findByRole("option", { name: "Trending this week" });
    await fireEvent.change(screen.getByLabelText("Chart TMDB chart"), {
      target: { value: "trending_week" },
    });
    await fireEvent.input(screen.getByLabelText("Chart chart length"), {
      target: { value: "25" },
    });
    expect($state.snapshot(chart)).toEqual({
      type: "tmdb_chart",
      chart: "trending_week",
      limit: 25,
    });
  });
});
