import { fireEvent, screen, waitFor, within } from "@testing-library/svelte";
import { beforeEach, describe, expect, it } from "vitest";
import type {
  CollectionGroupPolicyOutput,
  CollectionSourceInput,
  FilterGroupInput,
  FieldConditionInput,
} from "../../../generated/rest/types.gen";
import GroupSettingsHarness from "../../helpers/GroupSettingsHarness.svelte";
import CollectionPolicyFields, {
  type PolicyData,
} from "../../../lib/components/CollectionPolicyFields.svelte";
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
  dimension,
} from "../../helpers/fixtures";
import { renderWithQueryClient } from "../../helpers/render";

const capabilities = collectionCapabilities();
const members = [mediaItem({ id: 1, title: "First", library_id: "movies", server_item_id: "m1" })];
const detail = collectionDetail({
  id: 12,
  title: "Saga",
  library_ids: ["movies"],
  member_ids: members.map((member) => member.id),
  child_count: 1,
});
const rule = collectionRule();

describe("collection criteria", () => {
  beforeEach(async () => {
    queryClient.clear();
    settingsState.load(appSettings({ media_server: "plex", collections_supported: true }));
    await navigate("/collections/:collectionSlug", {
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
    await waitFor(() =>
      expect(document.querySelector('datalist option[value="Action"]')).toHaveTextContent(
        "3 titles",
      ),
    );
    const value = screen.getByRole("combobox", { name: "Criteria condition 1 value" });
    await fireEvent.input(value, { target: { value: "Action" } });

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

  it("duplicates, copies and pastes conditions and groups", async () => {
    mockFetchRoutes({ "/api/collections/field-values": [] });
    const genre = { kind: "field" as const, field: "genre" as const, operator: "is" as const };
    const source = $state<FilterGroupInput>({
      ...emptyGroup(),
      conditions: [{ ...genre, value: "Action" }],
      groups: [{ mode: "any", conditions: [{ ...genre, value: "Drama" }], groups: [] }],
    });
    const target = $state<FilterGroupInput>(emptyGroup());
    const props = {
      fields: capabilities.fields,
      sources: capabilities.sources,
      mediaType: "movie" as const,
      libraryId: "movies",
    };
    renderWithQueryClient(CriteriaEditor, { ...props, group: source, label: "Source" });
    renderWithQueryClient(CriteriaEditor, { ...props, group: target, label: "Target" });
    expect(screen.queryByRole("button", { name: /^Paste copied/ })).toBeNull();

    await fireEvent.click(screen.getByRole("button", { name: "Duplicate Source condition 1" }));
    await fireEvent.click(screen.getByRole("button", { name: "Duplicate Source group 1" }));
    expect($state.snapshot(source.conditions)).toEqual([
      { ...genre, value: "Action" },
      { ...genre, value: "Action" },
    ]);
    expect(source.groups).toHaveLength(2);
    // A duplicate is its own condition, not a second view of the first.
    await fireEvent.input(screen.getByLabelText("Source condition 2 value"), {
      target: { value: "Comedy" },
    });
    expect(source.conditions?.[0]).toMatchObject({ value: "Action" });

    await fireEvent.click(screen.getByRole("button", { name: "Copy Source condition 2" }));
    const paste = screen.getByRole("button", { name: "Paste copied condition into Target" });
    await fireEvent.click(paste);
    await fireEvent.click(paste);
    expect($state.snapshot(target.conditions)).toEqual([
      { ...genre, value: "Comedy" },
      { ...genre, value: "Comedy" },
    ]);
    await fireEvent.click(screen.getByRole("button", { name: "Copy Source group 1" }));
    await fireEvent.click(screen.getByRole("button", { name: "Paste copied group into Target" }));
    expect($state.snapshot(target.groups)).toEqual([
      { mode: "any", conditions: [{ ...genre, value: "Drama" }], groups: [] },
    ]);
  });

  it("types any tag value, suggesting the library's, and allows text for partial matches", async () => {
    mockFetchRoutes({
      "/api/collections/field-values": [{ value: "Action", count: 3 }],
    });
    const group = $state<FilterGroupInput>({
      ...emptyGroup(),
      conditions: [{ kind: "field", field: "genre", operator: "is", value: "Future genre" }],
    });
    renderWithQueryClient(CriteriaEditor, {
      group,
      fields: capabilities.fields,
      sources: capabilities.sources,
      mediaType: "movie",
      libraryId: "movies",
      label: "Criteria",
    });
    const value = screen.getByLabelText("Criteria condition 1 value");
    // A value the library lacks, as a preset fills in, shows as it is.
    expect(value.tagName).toBe("INPUT");
    expect(value).toHaveValue("Future genre");
    await fireEvent.input(value, { target: { value: "" } });
    await waitFor(() =>
      expect(document.querySelector('datalist option[value="Action"]')).not.toBeNull(),
    );
    await fireEvent.input(value, { target: { value: "christmas" } });
    expect(group.conditions?.[0]).toMatchObject({ value: "christmas" });
    await fireEvent.change(screen.getByLabelText("Criteria condition 1 field"), {
      target: { value: "field:title" },
    });
    await fireEvent.change(screen.getByLabelText("Criteria condition 1 operator"), {
      target: { value: "contains" },
    });
    const input = screen.getByLabelText("Criteria condition 1 value");
    expect(input.tagName).toBe("INPUT");
    await fireEvent.input(input, { target: { value: "Future" } });
    expect(group.conditions?.[0]).toMatchObject({ operator: "contains", value: "Future" });
  });

  it("suggests at most 50 library values, narrowed to what is typed", async () => {
    mockFetchRoutes({
      "/api/collections/field-values": Array.from({ length: 300 }, (_, index) => ({
        value: `Studio ${index}`,
        count: 1,
      })),
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
    const options = () => document.querySelectorAll(`#${value.getAttribute("list")} option`);

    await waitFor(() => expect(options()).toHaveLength(50));
    await fireEvent.input(value, { target: { value: "studio 29" } });
    // Studio 29 and Studio 290 to 299.
    await waitFor(() => expect(options()).toHaveLength(11));
  });

  it.each([
    { kind: "field", field: "unplayed", operator: "is", value: true },
    { kind: "field", field: "year", operator: "gte", value: 2020 },
    { kind: "field", field: "added", operator: "in_last", value: 7 },
  ] satisfies FieldConditionInput[])(
    "keeps $field values typed while editing",
    async (condition) => {
      const group = $state<FilterGroupInput>({ ...emptyGroup(), conditions: [condition] });
      renderWithQueryClient(CriteriaEditor, {
        group,
        fields: capabilities.fields,
        sources: capabilities.sources,
        mediaType: "movie",
        libraryId: "movies",
        label: "Criteria",
      });
      const input = screen.getByLabelText("Criteria condition 1 value");
      if (condition.field === "unplayed") {
        await fireEvent.change(input, { target: { value: "false" } });
        expect(group.conditions?.[0]).toMatchObject({ value: false });
        await fireEvent.change(input, { target: { value: "true" } });
        expect(group.conditions?.[0]).toMatchObject({ value: true });
      } else {
        await fireEvent.input(input, { target: { value: "0" } });
        expect(group.conditions?.[0]).toMatchObject({ value: 0 });
        await fireEvent.input(input, { target: { value: "12" } });
        expect(group.conditions?.[0]).toMatchObject({ value: 12 });
      }
    },
  );

  it("can replace a saved field that this server no longer offers", async () => {
    mockFetchRoutes({ "/api/collections/field-values": [] });
    const group = $state<FilterGroupInput>({
      ...emptyGroup(),
      conditions: [{ kind: "field", field: "studio", operator: "is", value: "Studio" }],
    });
    renderWithQueryClient(CriteriaEditor, {
      group,
      fields: capabilities.fields,
      sources: capabilities.sources,
      mediaType: "movie",
      libraryId: "movies",
      label: "Criteria",
    });
    expect(screen.getByRole("option", { name: "Unavailable field" })).toBeDisabled();
    await fireEvent.change(screen.getByLabelText("Criteria condition 1 field"), {
      target: { value: "field:title" },
    });
    await fireEvent.input(screen.getByLabelText("Criteria condition 1 value"), {
      target: { value: "Saga" },
    });
    expect(group.conditions?.[0]).toMatchObject({ field: "title", value: "Saga" });
  });

  it("retries unavailable choices and displays server choices without invented counts", async () => {
    let failed = true;
    mockFetchRoutes({
      "/api/collections/field-values": () =>
        failed
          ? Response.json({ detail: "Unavailable" }, { status: 422 })
          : Response.json([{ value: "English", count: 0 }]),
    });
    const group = $state<FilterGroupInput>({
      ...emptyGroup(),
      conditions: [{ kind: "field", field: "genre", operator: "is", value: "" }],
    });
    renderWithQueryClient(CriteriaEditor, {
      group,
      fields: capabilities.fields,
      sources: capabilities.sources,
      mediaType: "movie",
      libraryId: "movies",
      label: "Criteria",
    });
    const retry = await screen.findByRole("button", { name: "Retry available values" });
    failed = false;
    await fireEvent.click(retry);
    await waitFor(() => {
      const option = document.querySelector('datalist option[value="English"]');
      expect(option).not.toBeNull();
      expect(option).toHaveTextContent("");
    });
    await fireEvent.input(screen.getByLabelText("Criteria condition 1 value"), {
      target: { value: "English" },
    });
    expect(group.conditions?.[0]).toMatchObject({ value: "English" });
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
      person_name: null,
      roles: ["director"],
    });

    await fireEvent.click(await screen.findByRole("button", { name: "criterion" }));
    expect($state.snapshot(tags)).toEqual({ type: "radarr_tag", tags: ["criterion"] });
    expect(screen.getByRole("button", { name: "criterion" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("shows a tag the condition names even when Radarr lacks it", async () => {
    mockFetchRoutes({ "/api/collections/tags/radarr": [{ id: 1, label: "criterion" }] });
    const tags = $state<CollectionSourceInput>({ type: "radarr_tag", tags: ["requested"] });
    renderWithQueryClient(SourceFields, { source: tags, mediaType: "movie", label: "Tags" });

    const named = await screen.findByRole("button", { name: "requested" });
    expect(named).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "criterion" })).toHaveAttribute(
      "aria-pressed",
      "false",
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

    // One field searches and then holds the chosen ID.
    const personField = screen.getByLabelText("Person TMDB person ID");
    await fireEvent.input(personField, { target: { value: "Nolan" } });
    expect(personField).toBeInvalid();
    await fireEvent.click(screen.getByRole("button", { name: "Search Person" }));
    await fireEvent.click(await screen.findByRole("button", { name: /Christopher Nolan/ }));
    expect($state.snapshot(person)).toMatchObject({
      person_id: 525,
      person_name: "Christopher Nolan",
    });
    expect(personField).toHaveValue("525");
    expect(personField).toBeValid();

    const sagaField = screen.getByLabelText("Saga TMDB franchise ID");
    await fireEvent.input(sagaField, { target: { value: "Star Wars" } });
    await fireEvent.keyDown(sagaField, { key: "Enter" });
    await fireEvent.click(await screen.findByRole("button", { name: "Star Wars Collection" }));
    expect($state.snapshot(franchise)).toEqual({ type: "tmdb_collection", collection_id: 10 });
    expect(sagaField).toHaveValue("10");
    expect(screen.getByText("Star Wars Collection")).toBeInTheDocument();
  });

  it("names inherited values and keeps member effects off the global level", () => {
    const collectionPolicy = $state<PolicyData>({ sync_mode: null });
    const collection = renderWithQueryClient(CollectionPolicyFields, {
      policy: collectionPolicy,
      level: "collection",
      defaults: { sync_mode: "append" },
      arr: "Radarr",
      memberLabels: true,
    });
    expect(screen.getByRole("option", { name: "Default (Append)" })).toBeInTheDocument();
    expect(screen.getByLabelText("Member label")).toBeInTheDocument();
    expect(screen.getByLabelText("Radarr tag")).toBeInTheDocument();
    collection.unmount();

    const globalPolicy = $state<PolicyData>({ sync_mode: "sync" });
    renderWithQueryClient(CollectionPolicyFields, {
      policy: globalPolicy,
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
    const policy = $state<PolicyData>({ order_type: null });
    renderWithQueryClient(CollectionPolicyFields, {
      policy,
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

    await fireEvent.click(content.getByLabelText("Smart"));
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
      libraries: rule.libraries,
    });
  });

  it("switches either way, dropping a custom order smart cannot keep", async () => {
    let saved: unknown = null;
    const custom = { ...rule, order_type: "custom" as const };
    mockFetchRoutes({
      "/api/collections/defaults": {},
      "/api/collections/groups": [],
      "/api/collections/capabilities": capabilities,
      "/api/collections/12": ({ init }: { init: RequestInit }) =>
        Response.json(init.method === "PUT" ? detail : { ...detail, rule: custom }),
      "/api/collections/12/rule": ({ init }: { init: RequestInit }) => {
        saved = JSON.parse(String(init.body));
        return Response.json(custom);
      },
    });
    goToCollectionView(detail, "configure");
    renderWithQueryClient(CollectionPage);

    const content = within(await screen.findByRole("region", { name: "Collection content" }));
    await fireEvent.click(await content.findByLabelText("Smart"));
    await fireEvent.click(content.getByLabelText("Regular"));
    await fireEvent.click(content.getByLabelText("Smart"));
    await fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(saved).not.toBeNull());
    expect(saved).toMatchObject({ smart: true });
    expect(saved).not.toHaveProperty("order_type", "custom");
  });

  it("saves display, seasonal and Plex visibility choices", async () => {
    let putBody: unknown = null;
    // Per-user filtering is a smart collection's.
    const smartRule = { ...rule, smart: true };
    mockFetchRoutes({
      "/api/collections/12/rule": smartRule,
      "/api/collections/defaults": {},
      "/api/collections/groups": [],
      "/api/collections/capabilities": capabilities,
      "/api/library/libraries": [{ id: "movies", title: "Movies", media_type: "movie", count: 1 }],
      "/api/library/items": { items: members, total: 1 },
      "/api/collections/12": ({ init }: { init: RequestInit }) => {
        if (init.method === "PUT") {
          putBody = JSON.parse(String(init.body));
          return Response.json({ ...detail, ...JSON.parse(String(init.body)) });
        }
        return Response.json({ ...detail, kind: "smart", rule: smartRule });
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
      separator: false,
      sync_mode: null,
      minimum_items: 2,
      delete_below_minimum: null,
      auto_match_art: null,
      auto_generate_art: null,
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
    renderWithQueryClient(GroupSettingsHarness, {
      group: "Genres",
      libraries: [{ id: "movies", title: "Movies", media_type: "movie", count: 10 }],
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
      libraries: [{ id: "movies", title: "Movies", media_type: "movie", count: 1 }],
      capabilities: collectionCapabilities({
        dimensions: [
          ...capabilities.dimensions,
          dimension({
            dimension: "audio_language",
            label: "Audio languages",
            smart_only: true,
          }),
        ],
      }),
      group: "Mine",
      minimum: null,
      standalone: true,
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
