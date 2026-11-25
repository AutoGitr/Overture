import type { PolicyData } from "../../../lib/utils/collectionFormShared.svelte";
import { fireEvent, screen, waitFor, within } from "@testing-library/svelte";
import { tick } from "svelte";
import { beforeEach, describe, expect, it } from "vitest";
import type {
  CollectionSourceOutput,
  FilterGroupOutput,
  FieldConditionOutput,
} from "../../../generated/rest/types.gen";
import CollectionPolicyFields from "../../../lib/components/CollectionPolicyFields.svelte";
import CollectionSetEditor from "../../../lib/components/CollectionSetEditor.svelte";
import GlobalCollectionDefaults from "../../../lib/components/GlobalCollectionDefaults.svelte";
import CriteriaEditor from "../../../lib/components/CriteriaEditor.svelte";
import SourceFields from "../../../lib/components/SourceFields.svelte";
import CollectionPage from "../../../lib/router/pages/CollectionPage.svelte";
import { queryClient } from "../../../lib/rest/queryClient";
import { goToCollectionView, navigate } from "../../../lib/router/routes";
import { settingsState } from "../../../lib/stores/settingsState.svelte";
import { emptyGroup, newSource } from "../../../lib/utils/collectionCriteria";
import { defaultGenerator, withDimension } from "../../../lib/utils/collectionFormShared.svelte";
import { mockFetchRoutes } from "../../helpers/fetch";
import {
  appSettings,
  collectionCapabilities,
  collectionDetail,
  collectionRule,
  mediaItem,
  dimension,
  mediaServers,
} from "../../helpers/fixtures";
import { chooseOption, renderWithQueryClient } from "../../helpers/render";

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
    settingsState.load(
      appSettings({ media_servers: mediaServers("plex"), collections_supported: true }),
    );
    await navigate("/collections/:collectionSlug", {
      params: { collectionSlug: "12-saga" },
    });
  });

  it("builds field and source conditions in nested any and all groups", async () => {
    mockFetchRoutes({
      "/api/collections/field-values": [{ value: "Action", label: "Action", count: 3 }],
    });
    const group = $state<FilterGroupOutput>(emptyGroup());
    renderWithQueryClient(CriteriaEditor, {
      group,
      fields: capabilities.fields.filter((field) => field.local),
      sources: capabilities.sources,
      mediaType: "movie",
      libraryId: "movies",
      scope: "Movies on Plex",
      label: "Criteria",
    });

    await fireEvent.click(screen.getByRole("button", { name: "Condition" }));
    await chooseOption(screen.getByLabelText("Criteria condition 1 field"), "Genre");
    // The library's genres are listed, with how many titles hold each.
    await fireEvent.focus(screen.getByRole("combobox", { name: "Criteria condition 1 value" }));
    await fireEvent.click(await screen.findByRole("option", { name: /^Action\s*3 titles$/ }));

    await fireEvent.click(screen.getByRole("button", { name: "Group" }));
    const nested = within(screen.getByRole("group", { name: "Criteria group 1" }));
    await fireEvent.click(nested.getByRole("button", { name: "Condition" }));
    const subject = nested.getByLabelText("Criteria group 1 condition 1 field");
    await fireEvent.click(subject);
    expect(screen.getByRole("option", { name: /Sonarr tags/ })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    await fireEvent.click(screen.getByRole("option", { name: "MDBList" }));
    await chooseOption(nested.getByLabelText("Criteria group 1 condition 1 operator"), "not in");
    await fireEvent.change(nested.getByLabelText("Criteria group 1 condition 1 MDBList lists"), {
      target: { value: "user/list, other/list" },
    });
    await fireEvent.click(nested.getByRole("button", { name: "Condition" }));
    await chooseOption(nested.getByLabelText("Criteria group 1 condition 2 field"), "Date added");
    await chooseOption(nested.getByLabelText("Criteria group 1 condition 2 operator"), "is after");
    await fireEvent.input(nested.getByLabelText("Criteria group 1 condition 2 value"), {
      target: { value: "2020-01-31" },
    });
    await chooseOption(screen.getByLabelText("Criteria match"), "any");

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
    mockFetchRoutes({
      "/api/collections/field-values": ["Action", "Comedy", "Drama"].map((value) => ({
        value,
        label: value,
        count: 1,
      })),
    });
    const genre = { kind: "field" as const, field: "genre" as const, operator: "is" as const };
    const source = $state<FilterGroupOutput>({
      ...emptyGroup(),
      conditions: [{ ...genre, value: "Action" }],
      groups: [{ mode: "any", conditions: [{ ...genre, value: "Drama" }], groups: [] }],
    });
    const target = $state<FilterGroupOutput>(emptyGroup());
    const props = {
      fields: capabilities.fields,
      sources: capabilities.sources,
      mediaType: "movie" as const,
      libraryId: "movies",
      scope: "Movies on Plex",
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
    await fireEvent.input(screen.getByRole("combobox", { name: "Source condition 2 value" }), {
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

  it("types a tag value, as many as the library holds, and narrows the list to what is typed", async () => {
    mockFetchRoutes({
      "/api/collections/field-values": Array.from({ length: 600 }, (_, index) => ({
        value: `Actor ${index}`,
        label: `Actor ${index}`,
        count: 1,
      })),
    });
    const group = $state<FilterGroupOutput>({
      ...emptyGroup(),
      conditions: [{ kind: "field", field: "genre", operator: "is", value: "Future genre" }],
    });
    renderWithQueryClient(CriteriaEditor, {
      group,
      fields: capabilities.fields,
      sources: capabilities.sources,
      mediaType: "movie",
      libraryId: "movies",
      scope: "Movies on Plex",
      label: "Criteria",
    });
    const value = screen.getByRole("combobox", { name: "Criteria condition 1 value" });
    // A value no title has, as a saved filter may hold, shows as it is.
    expect(value).toHaveValue("Future genre");

    await fireEvent.focus(value);
    const listed = () => within(screen.getByRole("listbox")).getAllByRole("option");
    await waitFor(() => expect(listed()).toHaveLength(50));
    await fireEvent.input(value, { target: { value: "actor 29" } });
    // Actor 29 and Actor 290 to 299, matched ignoring case.
    expect(listed()).toHaveLength(11);
    expect(group.conditions?.[0]).toMatchObject({ value: "actor 29" });
    await fireEvent.keyDown(value, { key: "ArrowDown" });
    await fireEvent.keyDown(value, { key: "ArrowDown" });
    await fireEvent.keyDown(value, { key: "Enter" });
    expect(group.conditions?.[0]).toMatchObject({ value: "Actor 290" });
    expect(value).toHaveValue("Actor 290");
    expect(screen.queryByRole("listbox")).toBeNull();

    await chooseOption(screen.getByLabelText("Criteria condition 1 field"), "Title");
    await chooseOption(screen.getByLabelText("Criteria condition 1 operator"), "contains");
    await fireEvent.input(screen.getByRole("combobox", { name: "Criteria condition 1 value" }), {
      target: { value: "Future" },
    });
    expect(group.conditions?.[0]).toMatchObject({ operator: "contains", value: "Future" });
  });

  it("chooses a collection by its title and keeps its ID, naming one that holds no title", async () => {
    mockFetchRoutes({
      "/api/collections/field-values": [
        { value: "7", label: "Letterboxd Top 250", count: 238 },
        { value: "8", label: "IMDb Top 250", count: 250 },
      ],
    });
    const collection = capabilities.fields.find((field) => field.field === "genre")!;
    const group = $state<FilterGroupOutput>({
      ...emptyGroup(),
      conditions: [{ kind: "field", field: "genre", operator: "is", value: "12" }],
    });
    renderWithQueryClient(CriteriaEditor, {
      group,
      fields: [{ ...collection, label: "Collection", by_id: true }],
      sources: capabilities.sources,
      mediaType: "movie",
      libraryId: "movies",
      scope: "Movies on Plex",
      label: "Criteria",
    });
    const value = screen.getByRole("combobox", { name: "Criteria condition 1 value" });
    await waitFor(() => expect(value).toHaveValue("Genre #12 (holds no title)"));

    await fireEvent.focus(value);
    await fireEvent.input(value, { target: { value: "letterboxd" } });
    // A typed title is no ID: only a listed collection is held.
    expect(group.conditions?.[0]).toMatchObject({ value: "12" });
    await fireEvent.click(screen.getByRole("option", { name: /^Letterboxd Top 250/ }));
    expect(group.conditions?.[0]).toMatchObject({ value: "7" });
    expect(value).toHaveValue("Letterboxd Top 250");

    // A title typed whole is taken; anything else leaves the choice as it was.
    await fireEvent.input(value, { target: { value: "imdb top 250" } });
    await fireEvent.blur(value);
    expect(group.conditions?.[0]).toMatchObject({ value: "8" });
    await fireEvent.input(value, { target: { value: "Nothing like it" } });
    await fireEvent.blur(value);
    expect(group.conditions?.[0]).toMatchObject({ value: "8" });
    expect(value).toHaveValue("IMDb Top 250");
  });

  it.each([
    { kind: "field", field: "unplayed", operator: "is", value: true },
    { kind: "field", field: "year", operator: "gte", value: 2020 },
    { kind: "field", field: "added", operator: "in_last", value: 7 },
  ] satisfies FieldConditionOutput[])(
    "keeps $field values typed while editing",
    async (condition) => {
      const group = $state<FilterGroupOutput>({ ...emptyGroup(), conditions: [condition] });
      renderWithQueryClient(CriteriaEditor, {
        group,
        fields: capabilities.fields,
        sources: capabilities.sources,
        mediaType: "movie",
        libraryId: "movies",
        scope: "Movies on Plex",
        label: "Criteria",
      });
      const input = screen.getByLabelText("Criteria condition 1 value");
      if (condition.field === "unplayed") {
        await chooseOption(input, "false");
        expect(group.conditions?.[0]).toMatchObject({ value: false });
        await chooseOption(input, "true");
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
    const group = $state<FilterGroupOutput>({
      ...emptyGroup(),
      conditions: [{ kind: "field", field: "studio", operator: "is", value: "Studio" }],
    });
    renderWithQueryClient(CriteriaEditor, {
      group,
      fields: capabilities.fields,
      sources: capabilities.sources,
      mediaType: "movie",
      libraryId: "movies",
      scope: "Movies on Plex",
      label: "Criteria",
    });
    const fieldPicker = screen.getByLabelText("Criteria condition 1 field");
    expect(fieldPicker).toHaveTextContent("Studio (unavailable)");
    await fireEvent.click(fieldPicker);
    expect(screen.queryByRole("option", { name: /Studio/ })).toBeNull();
    expect(
      screen.getByText("Studio cannot be tested for Movies on Plex; choose another field."),
    ).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("option", { name: "Title" }));
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
          : Response.json([{ value: "English", label: "English", count: 0 }]),
    });
    const group = $state<FilterGroupOutput>({
      ...emptyGroup(),
      conditions: [{ kind: "field", field: "genre", operator: "is", value: "" }],
    });
    renderWithQueryClient(CriteriaEditor, {
      group,
      fields: capabilities.fields,
      sources: capabilities.sources,
      mediaType: "movie",
      libraryId: "movies",
      scope: "Movies on Plex",
      label: "Criteria",
    });
    const retry = await screen.findByRole("button", { name: "Retry available values" });
    failed = false;
    await fireEvent.click(retry);
    // Plex lists its values without counts, so none are shown.
    const value = screen.getByRole("combobox", { name: "Criteria condition 1 value" });
    await fireEvent.focus(value);
    await fireEvent.click(await screen.findByRole("option", { name: "English" }));
    expect(group.conditions?.[0]).toMatchObject({ value: "English" });
  });

  it("edits person credits and offers the configured Radarr tags", async () => {
    mockFetchRoutes({ "/api/collections/tags/radarr": [{ id: 1, label: "criterion" }] });
    const person = $state<CollectionSourceOutput>({
      type: "tmdb_person",
      person_id: 0,
      person_name: null,
      roles: ["actor"],
    });
    const tags = $state<CollectionSourceOutput>({ type: "radarr_tag", tags: [] });
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
    const tags = $state<CollectionSourceOutput>({ type: "radarr_tag", tags: ["requested"] });
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
    const person = $state<CollectionSourceOutput>(newSource("tmdb_person"));
    const franchise = $state<CollectionSourceOutput>({ type: "tmdb_collection", collection_id: 0 });
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

  it("names inherited values and keeps member effects off the global level", async () => {
    const collectionPolicy = $state<PolicyData>({ sync_mode: null });
    const collection = renderWithQueryClient(CollectionPolicyFields, {
      policy: collectionPolicy,
      level: "collection",
      defaults: { sync_mode: "append" },
      arr: "Radarr",
      memberLabels: true,
    });
    expect(screen.getByLabelText("Sync mode")).toHaveTextContent("Default (Append)");
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
    await fireEvent.click(screen.getByLabelText("Sync mode"));
    expect(screen.queryByRole("option", { name: /^Default/ })).toBeNull();
    expect(screen.queryByLabelText("Member label")).toBeNull();
    expect(screen.queryByLabelText("Radarr tag")).toBeNull();
    expect(screen.getByLabelText("Request missing")).toBeInTheDocument();
  });

  it("keeps Automatic theme in view but off while themes are not needed", () => {
    const policy = $state<PolicyData>({ themes: null, auto_match_theme: true });
    renderWithQueryClient(CollectionPolicyFields, {
      policy,
      level: "collection",
      defaults: { themes: false },
    });
    expect(screen.getByLabelText("Automatic theme")).toBeDisabled();
  });

  it("offers the sorts the server supports", async () => {
    const policy = $state<PolicyData>({ order_type: null });
    renderWithQueryClient(CollectionPolicyFields, {
      policy,
      level: "collection",
      orders: ["custom", "critic_rating.desc"],
    });
    await fireEvent.click(screen.getByLabelText("Sort"));
    expect(
      within(screen.getByRole("listbox"))
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
    await fireEvent.click(field);
    expect(screen.queryByRole("option", { name: "HDR" })).toBeNull();
    await fireEvent.keyDown(field, { key: "Escape" });

    const sort = settings.getByLabelText("Sort");
    await fireEvent.click(sort);
    expect(screen.getByRole("option", { name: /^Custom/ })).toBeInTheDocument();
    await fireEvent.keyDown(sort, { key: "Escape" });

    await fireEvent.click(content.getByLabelText("Smart"));
    await fireEvent.click(field);
    expect(screen.getByRole("option", { name: "HDR" })).toBeInTheDocument();
    await fireEvent.keyDown(field, { key: "Escape" });

    await fireEvent.click(sort);
    expect(screen.queryByRole("option", { name: /^Custom/ })).toBeNull();
    await fireEvent.click(screen.getByRole("option", { name: "Critic rating (highest first)" }));
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
      "/api/library/libraries": [
        { id: "movies", title: "Movies", media_type: "movie", server_id: 1, count: 1 },
      ],
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
    await fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    await fireEvent.input(display.getByLabelText(/^Summary$/i), {
      target: { value: "{title} - {group}" },
    });
    const schedule = within(screen.getByRole("region", { name: "Collection schedule" }));
    await fireEvent.click(screen.getByRole("button", { name: "Active dates" }));
    await fireEvent.input(schedule.getByLabelText(/^Active from/i), {
      target: { value: "12-15" },
    });
    await fireEvent.input(schedule.getByLabelText(/^Active until/i), {
      target: { value: "01-05" },
    });
    await chooseOption(await display.findByLabelText(/Shared users' home/i), "Show");
    await chooseOption(display.getByLabelText(/Collection filtering/i), "Admin's library");
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

  it("lists a custom set's collections and renames or merges other values", async () => {
    const generator = $state(defaultGenerator(["movies"]));
    const custom = dimension({ dimension: "custom", label: "Custom" });
    const audio = dimension({
      dimension: "audio_language",
      label: "Audio languages",
      smart_only: true,
    });
    /** Split the set as Setup's Split by does. */
    const split = async (chosen: typeof custom) => {
      const previous = [custom, audio].find((entry) => entry.dimension === generator.dimension);
      Object.assign(generator, withDimension(generator, chosen, previous));
      await tick();
    };
    renderWithQueryClient(CollectionSetEditor, {
      generator,
      libraryIds: ["movies"],
      libraries: [{ id: "movies", title: "Movies", media_type: "movie", server_id: 1, count: 1 }],
      capabilities: collectionCapabilities({
        dimensions: [...capabilities.dimensions, audio],
      }),
      group: "Mine",
      minimum: null,
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

    await split(custom);
    expect(generator.custom_values).toHaveLength(1);
    await fireEvent.click(screen.getByRole("button", { name: "Add collection" }));
    await fireEvent.input(screen.getByLabelText("Collection 2 name"), {
      target: { value: "B" },
    });
    expect(generator.custom_values?.map((value) => value.name)).toEqual(["", "B"]);
    await fireEvent.click(screen.getAllByRole("button", { name: "Remove" })[0]!);
    expect(generator.custom_values?.map((value) => value.name)).toEqual(["B"]);

    await split(audio);
    expect(generator.smart).toBe(true);
    expect(generator.custom_values).toEqual([]);
  });

  it("edits the global defaults under their own names and where requests go", async () => {
    settingsState.load(
      appSettings({
        media_servers: mediaServers("plex"),
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
    await chooseOption(screen.getByLabelText("Sync mode"), "Append");
    expect(draft.collection_sync_mode).toBe("append");
    await fireEvent.input(screen.getByLabelText("Sort title"), { target: { value: "" } });
    expect(draft.collection_sort_title_format).toBe("");
    await chooseOption(screen.getByLabelText("Collection mode"), "Hide collection");
    expect(draft.collection_mode_default).toBe("hide");
    await fireEvent.input(screen.getByLabelText("TMDB region"), { target: { value: "SE" } });
    expect(draft.tmdb_region).toBe("SE");
    await chooseOption(screen.getByLabelText("Radarr root folder"), "/movies");
    expect(draft.radarr_root_folder).toBe("/movies");
    expect(screen.queryByLabelText("Sonarr root folder")).toBeNull();
    await fireEvent.click(screen.getByLabelText("Sync mode"));
    expect(screen.queryByRole("option", { name: /^Default/ })).toBeNull();
  });

  it("picks a TMDB chart and how many of its titles count", async () => {
    mockFetchRoutes({ "/api/collections/capabilities": capabilities });
    const chart = $state<CollectionSourceOutput>({
      type: "tmdb_chart",
      chart: "popular",
      limit: 100,
    });
    renderWithQueryClient(SourceFields, { source: chart, mediaType: "movie", label: "Chart" });
    await chooseOption(screen.getByLabelText("Chart TMDB chart"), "Trending this week");
    await fireEvent.input(screen.getByLabelText("Chart chart length"), {
      target: { value: "25" },
    });
    expect($state.snapshot(chart)).toEqual({
      type: "tmdb_chart",
      chart: "trending_week",
      limit: 25,
    });
  });

  it("groups criteria sources under Lists & tags", async () => {
    const group = $state<FilterGroupOutput>(emptyGroup());
    renderWithQueryClient(CriteriaEditor, {
      group,
      fields: capabilities.fields,
      sources: capabilities.sources,
      mediaType: "movie",
      libraryId: "movies",
      scope: "Movies on Plex",
      label: "Criteria",
    });
    await fireEvent.click(screen.getByRole("button", { name: "Condition" }));
    await fireEvent.click(screen.getByLabelText("Criteria condition 1 field"));
    expect(screen.getByText("Lists & tags")).toBeInTheDocument();
  });

  it("offers manual TMDB IDs without TMDB configured and adds title search when configured", async () => {
    settingsState.load(appSettings({ tmdb_configured: false }));
    const source = $state<CollectionSourceOutput>({
      type: "tmdb_item",
      tmdb_ids: [550],
    });
    const { rerender } = renderWithQueryClient(SourceFields, {
      source,
      mediaType: "movie",
      label: "Title list",
    });

    expect(screen.getByLabelText("Title list TMDB IDs")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Search TMDB movies to add")).toBeNull();

    settingsState.load(appSettings({ tmdb_configured: true }));
    await rerender({});
    expect(screen.getByPlaceholderText("Search TMDB movies to add")).toBeInTheDocument();
  });
});
