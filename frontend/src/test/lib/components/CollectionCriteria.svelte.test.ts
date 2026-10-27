import { fireEvent, screen, waitFor, within } from "@testing-library/svelte";
import { beforeEach, describe, expect, it } from "vitest";
import type {
  CollectionGroupPolicyOutput,
  CollectionSourceInput,
  FilterGroupInput,
} from "../../../generated/rest/types.gen";
import CollectionGroupSettings from "../../../lib/components/CollectionGroupSettings.svelte";
import CollectionPolicyFields from "../../../lib/components/CollectionPolicyFields.svelte";
import CriteriaEditor from "../../../lib/components/CriteriaEditor.svelte";
import SourceFields from "../../../lib/components/SourceFields.svelte";
import CollectionPage from "../../../lib/router/pages/CollectionPage.svelte";
import { queryClient } from "../../../lib/rest/queryClient";
import { goToCollectionView, navigate } from "../../../lib/router/routes";
import { settingsState } from "../../../lib/stores/settingsState.svelte";
import { emptyGroup } from "../../../lib/utils/collectionCriteria";
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
      use_biography: false,
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
    await fireEvent.click(credits.getByLabelText("Biography as summary"));
    expect($state.snapshot(person)).toEqual({
      type: "tmdb_person",
      person_id: 525,
      roles: ["director"],
      use_biography: true,
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

  it("offers the sorts the server supports", () => {
    renderWithQueryClient(CollectionPolicyFields, {
      policy: { order_type: null },
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
      sync_interval_hours: null,
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
    await fireEvent.change(screen.getByLabelText("One collection per"), {
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
      generator: { dimension: "genre", library_id: "movies", top: 10 },
    });

    await fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(putBody).not.toBeNull());
    expect(synced).toBe(false);
    expect(putBody).toMatchObject({
      minimum_items: 2,
      generator: { dimension: "genre", library_id: "movies", title_format: "{value}", top: 10 },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Save and Sync" }));
    await waitFor(() => expect(synced).toBe(true));
  });
});
