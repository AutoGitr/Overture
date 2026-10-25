import { fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type {
  CollectionBuilderInput,
  CollectionGroupPolicyOutput,
  FilterGroupInput,
} from "../../../generated/rest/types.gen";
import CollectionBuilderItem from "../../../lib/components/CollectionBuilderItem.svelte";
import CollectionGroupSettings from "../../../lib/components/CollectionGroupSettings.svelte";
import CollectionPolicyFields from "../../../lib/components/CollectionPolicyFields.svelte";
import FilterGroupEditor from "../../../lib/components/FilterGroupEditor.svelte";
import CollectionPage from "../../../lib/router/pages/CollectionPage.svelte";
import { queryClient } from "../../../lib/rest/queryClient";
import { goToCollectionView, navigate } from "../../../lib/router/routes";
import { settingsState } from "../../../lib/stores/settingsState.svelte";
import { emptyFilterGroup, newBuilder } from "../../../lib/utils/collectionBuilders";
import { mockFetchRoutes } from "../../helpers/fetch";
import { appSettings, collectionDetail, collectionRule, mediaItem } from "../../helpers/fixtures";
import { renderWithQueryClient } from "../../helpers/render";

const members = [mediaItem({ id: 1, title: "First", library_id: "movies", server_item_id: "m1" })];
const detail = collectionDetail({
  id: 12,
  title: "Saga",
  library_id: "movies",
  members,
  child_count: 1,
});
const rule = collectionRule({ builders: [{ type: "mdblist", identifiers: ["top10"] }] });

describe("Collection Builders UI", () => {
  beforeEach(async () => {
    queryClient.clear();
    settingsState.load(appSettings({ media_server: "plex", collections_supported: true }));
    await navigate("/movies/collections/:collectionSlug", {
      params: { collectionSlug: "12-saga" },
    });
  });

  describe("CollectionBuilderItem", () => {
    it("renders and edits a TMDB franchise builder", async () => {
      const builder: CollectionBuilderInput = { type: "tmdb_collection", collection_id: 10 };
      renderWithQueryClient(CollectionBuilderItem, {
        builder,
        mediaType: "movie",
      });

      expect(screen.getByRole("heading", { name: "TMDB franchise" })).toBeInTheDocument();
      const input = screen.getByLabelText(/TMDB franchise ID/i);
      expect(input).toHaveValue(10);
      await fireEvent.input(input, { target: { value: "86311" } });
    });

    it("renders and edits a TMDB item titles builder", async () => {
      const builder: CollectionBuilderInput = { type: "tmdb_item", tmdb_ids: [101, 102] };
      renderWithQueryClient(CollectionBuilderItem, {
        builder,
        mediaType: "movie",
      });

      expect(screen.getByRole("heading", { name: "TMDB titles" })).toBeInTheDocument();
      const textarea = screen.getByLabelText(/TMDB movie IDs/i);
      expect(textarea).toHaveValue("101, 102");
      await fireEvent.change(textarea, { target: { value: "550, 680" } });
    });

    it("renders and edits a TMDB person credits builder with roles and biography toggle", async () => {
      const builder: CollectionBuilderInput = {
        type: "tmdb_person",
        person_id: 138,
        person_name: "Quentin Tarantino",
        roles: ["director", "writer"],
        use_biography: true,
      };
      renderWithQueryClient(CollectionBuilderItem, {
        builder,
        mediaType: "movie",
      });

      expect(screen.getByRole("heading", { name: "TMDB person" })).toBeInTheDocument();
      expect(screen.getByDisplayValue("Quentin Tarantino")).toBeInTheDocument();
      expect(screen.getByDisplayValue("138")).toBeInTheDocument();
      const bioCheckbox = screen.getByLabelText(/Use person biography as collection summary/i);
      expect(bioCheckbox).toBeChecked();

      const actorCheckbox = screen.getByLabelText(/Actor \/ Cast/i);
      expect(actorCheckbox).not.toBeChecked();
      await fireEvent.click(actorCheckbox);
    });

    it("renders and edits an MDBList builder", async () => {
      const builder: CollectionBuilderInput = {
        type: "mdblist",
        identifiers: ["https://mdblist.com/lists/top10"],
      };
      renderWithQueryClient(CollectionBuilderItem, {
        builder,
        mediaType: "movie",
      });

      expect(screen.getByRole("heading", { name: "MDBList" })).toBeInTheDocument();
      const input = screen.getByLabelText(/MDBList list URL or ID/i);
      expect(input).toHaveValue("https://mdblist.com/lists/top10");
    });

    it("triggers reordering and removal callbacks", async () => {
      const onremove = vi.fn();
      const onmoveup = vi.fn();
      const onmovedown = vi.fn();

      renderWithQueryClient(CollectionBuilderItem, {
        builder: newBuilder("mdblist"),
        index: 1,
        total: 3,
        mediaType: "movie",
        onremove,
        onmoveup,
        onmovedown,
      });

      await fireEvent.click(screen.getByTitle("Move builder up"));
      expect(onmoveup).toHaveBeenCalledOnce();

      await fireEvent.click(screen.getByTitle("Move builder down"));
      expect(onmovedown).toHaveBeenCalledOnce();

      await fireEvent.click(screen.getByTitle("Remove builder"));
      expect(onremove).toHaveBeenCalledOnce();
    });

    it("renders and edits a Radarr tag builder with chips and text input", async () => {
      settingsState.load(
        appSettings({
          media_server: "plex",
          collections_supported: true,
          radarr_configured: true,
        }),
      );
      mockFetchRoutes({
        "/api/collections/tags/radarr": [
          { id: 1, label: "4k" },
          { id: 2, label: "favorite" },
        ],
      });

      const builder: CollectionBuilderInput = {
        type: "radarr_tag",
        tags: ["4k"],
      };

      renderWithQueryClient(CollectionBuilderItem, {
        builder,
        mediaType: "movie",
      });

      expect(screen.getByRole("heading", { name: "Radarr tags" })).toBeInTheDocument();
      const chip = await screen.findByRole("button", { name: "favorite" });
      await fireEvent.click(chip);
      expect(builder.tags).toContain("favorite");

      const input = screen.getByPlaceholderText(/Tag names separated by comma/i);
      await fireEvent.change(input, { target: { value: "anime, action" } });
      expect(builder.tags).toEqual(["anime", "action"]);
    });

    it("renders and edits a Sonarr tag builder with chips and text input", async () => {
      settingsState.load(
        appSettings({
          media_server: "plex",
          collections_supported: true,
          sonarr_configured: true,
        }),
      );
      mockFetchRoutes({
        "/api/collections/tags/sonarr": [
          { id: 1, label: "anime" },
          { id: 2, label: "hdr" },
        ],
      });

      const builder: CollectionBuilderInput = {
        type: "sonarr_tag",
        tags: ["hdr"],
      };

      renderWithQueryClient(CollectionBuilderItem, {
        builder,
        mediaType: "show",
      });

      expect(screen.getByRole("heading", { name: "Sonarr tags" })).toBeInTheDocument();
      const chip = await screen.findByRole("button", { name: "anime" });
      await fireEvent.click(chip);
      expect(builder.tags).toContain("anime");

      const input = screen.getByPlaceholderText(/Tag names separated by comma/i);
      await fireEvent.change(input, { target: { value: "scifi, comedy" } });
      expect(builder.tags).toEqual(["scifi", "comedy"]);
    });

    it("renders a library filter builder with nested filter group editor", async () => {
      const builder = $state<CollectionBuilderInput>({
        type: "library_filter",
        filter_group: {
          mode: "all",
          conditions: [{ field: "genre", operator: "is", value: "Drama" }],
          groups: [],
        },
      });

      renderWithQueryClient(CollectionBuilderItem, {
        builder,
        mediaType: "movie",
      });

      expect(screen.getByRole("heading", { name: "Library filter" })).toBeInTheDocument();
      expect(screen.getByDisplayValue("Drama")).toBeInTheDocument();
    });
  });

  describe("FilterGroupEditor", () => {
    it("renders an empty filter group and adds a condition", async () => {
      const group = $state<FilterGroupInput>(emptyFilterGroup());
      render(FilterGroupEditor, { group, label: "Criteria" });

      const conditionBtn = screen.getByRole("button", { name: "Condition" });
      expect(conditionBtn).toBeInTheDocument();
      await fireEvent.click(conditionBtn);

      expect(group.conditions?.length).toBe(1);
    });

    it("switches match mode between all and any", async () => {
      const group = $state<FilterGroupInput>({
        mode: "all",
        conditions: [{ field: "genre", operator: "is", value: "Action" }],
        groups: [],
      });
      render(FilterGroupEditor, { group, label: "Criteria" });

      const modeSelect = screen.getByLabelText(/Criteria match mode/i);
      expect(modeSelect).toHaveValue("all");
      await fireEvent.change(modeSelect, { target: { value: "any" } });
      expect(group.mode).toBe("any");
    });

    it("adds and removes nested filter groups", async () => {
      const group = $state<FilterGroupInput>({
        mode: "all",
        conditions: [],
        groups: [],
      });
      render(FilterGroupEditor, { group, label: "Outer criteria" });

      await fireEvent.click(screen.getByRole("button", { name: "Group" }));
      expect(group.groups?.length).toBe(1);

      await fireEvent.click(screen.getByRole("button", { name: /Remove Outer criteria group 1/i }));
      expect(group.groups?.length).toBe(0);
    });

    it("updates condition field, operator, and value, and removes condition", async () => {
      const group = $state<FilterGroupInput>({
        mode: "all",
        conditions: [{ field: "genre", operator: "is", value: "Drama" }],
        groups: [],
      });

      render(FilterGroupEditor, { group, label: "Criteria" });

      const fieldSelect = screen.getByLabelText("Criteria field 1");
      await fireEvent.change(fieldSelect, { target: { value: "studio" } });
      expect(group.conditions?.[0]?.field).toBe("studio");

      const opSelect = screen.getByLabelText("Criteria operator 1");
      await fireEvent.change(opSelect, { target: { value: "is_not" } });
      expect(group.conditions?.[0]?.operator).toBe("is_not");

      const valInput = screen.getByLabelText("Criteria value 1");
      await fireEvent.input(valInput, { target: { value: "Warner Bros" } });
      expect(group.conditions?.[0]?.value).toBe("Warner Bros");

      const removeBtn = screen.getByRole("button", { name: "Remove Criteria condition 1" });
      await fireEvent.click(removeBtn);
      expect(group.conditions?.length).toBe(0);
    });
  });

  describe("CollectionPolicyFields", () => {
    it("binds and edits policy strategy, minimums, and seasonal inactivity", async () => {
      const policy = $state({
        sync_mode: null,
        minimum_items: null,
        delete_below_minimum: null,
        auto_match_art: null,
        auto_match_theme: null,
        delete_when_inactive: null,
        collection_mode: null,
        collection_filtering: null,
        visible_shared: null,
        visible_library: null,
      });

      render(CollectionPolicyFields, {
        policy,
        prefix: "Test ",
        plex: true,
      });

      await fireEvent.change(screen.getByLabelText(/Test Sync strategy/i), {
        target: { value: "sync" },
      });
      expect(policy.sync_mode).toBe("sync");

      await fireEvent.input(screen.getByLabelText(/Test Minimum members/i), {
        target: { value: "5" },
      });
      expect(policy.minimum_items).toBe(5);

      await fireEvent.change(screen.getByLabelText(/Test Below minimum/i), {
        target: { value: "true" },
      });
      expect(policy.delete_below_minimum).toBe(true);

      await fireEvent.change(screen.getByLabelText(/Test Automatic artwork/i), {
        target: { value: "true" },
      });
      expect(policy.auto_match_art).toBe(true);

      await fireEvent.change(screen.getByLabelText(/Test Automatic themes/i), {
        target: { value: "false" },
      });
      expect(policy.auto_match_theme).toBe(false);

      await fireEvent.change(screen.getByLabelText(/Test When inactive \(seasonal\)/i), {
        target: { value: "true" },
      });
      expect(policy.delete_when_inactive).toBe(true);

      await fireEvent.change(screen.getByLabelText(/Test Visibility mode/i), {
        target: { value: "hide_items" },
      });
      expect(policy.collection_mode).toBe("hide_items");

      await fireEvent.change(screen.getByLabelText(/Test Collection filtering/i), {
        target: { value: "admin" },
      });
      expect(policy.collection_filtering).toBe("admin");
    });
  });

  describe("CollectionGroupSettings", () => {
    it("opens group defaults, configures dynamic TMDB discovery, saves, and syncs", async () => {
      let putBody: unknown = null;
      let syncCalled = false;

      const groupPolicy: CollectionGroupPolicyOutput = {
        sync_mode: "sync",
        minimum_items: 2,
        delete_below_minimum: false,
        auto_match_art: true,
        auto_match_theme: false,
        delete_when_inactive: false,
        collection_mode: null,
        collection_filtering: null,
        visible_shared: null,
        visible_library: null,
        sort_title_format: null,
        summary_format: null,
        active_start_mmdd: null,
        active_end_mmdd: null,
        dynamic_tmdb: null,
        sync_enabled: true,
        sync_interval_hours: 24,
        visible_home: null,
        order_type: null,
      };

      mockFetchRoutes({
        "/api/collections/group-policy": ({ init }: { init: RequestInit }) => {
          if (init.method === "PUT") {
            putBody = JSON.parse(init.body as string);
            return Response.json({ ...groupPolicy, ...JSON.parse(init.body as string) });
          }
          return Response.json(groupPolicy);
        },
        "/api/collections/group-policy/sync": () => {
          syncCalled = true;
          return Response.json({ status: "ok" });
        },
      });

      renderWithQueryClient(CollectionGroupSettings, {
        group: "Marvel",
        mediaType: "movie",
        serverType: "plex",
        libraries: [{ id: "movies", title: "Movies", count: 10 }],
      });

      const summary = screen.getByText(/Defaults for group: Marvel/i);
      expect(summary).toBeInTheDocument();

      // Open details
      await fireEvent.click(summary);

      // Wait for group defaults to load
      expect(
        await screen.findByRole("button", { name: "Save group defaults" }),
      ).toBeInTheDocument();

      // Toggle sort title inherit off and provide template
      const sortInherit = screen.getByLabelText(/Inherit global sort title template/i);
      await fireEvent.click(sortInherit);
      const sortInput = await screen.findByLabelText(/Group sort title template/i);
      await fireEvent.input(sortInput, { target: { value: "Marvel - {title}" } });

      // Toggle summary inherit off and provide template
      const summaryInherit = screen.getByLabelText(/Inherit global summary template/i);
      await fireEvent.click(summaryInherit);
      const summaryInput = await screen.findByLabelText(/Group summary template/i);
      await fireEvent.input(summaryInput, { target: { value: "{group}: {title}" } });

      // Enable dynamic TMDB discovery
      const dynamicToggle = screen.getByLabelText(
        /Auto-discover TMDB franchise collections from library movies/i,
      );
      await fireEvent.click(dynamicToggle);

      // Verify dynamic discovery fields
      const prefixInput = await screen.findByLabelText(/Strip prefix/i);
      await fireEvent.input(prefixInput, { target: { value: "MCU " } });

      const excludeInput = screen.getByLabelText(/Exclude TMDB franchise IDs/i);
      await fireEvent.change(excludeInput, { target: { value: "10, 20" } });

      // Save
      await fireEvent.click(screen.getByRole("button", { name: /Save group defaults/i }));
      await waitFor(() => expect(putBody).not.toBeNull());

      // Sync
      await fireEvent.click(screen.getByRole("button", { name: /Sync Group Now/i }));
      await waitFor(() => expect(syncCalled).toBe(true));
    });
  });

  describe("CollectionRulePanel & Configure", () => {
    it("configures Plex smart collection options and criteria", async () => {
      mockFetchRoutes({
        "/api/collections/groups": [],
        "/api/collections/12": { ...detail, kind: "smart", rule },
      });
      goToCollectionView(detail, "configure");
      renderWithQueryClient(CollectionPage);

      await fireEvent.change(await screen.findByLabelText("Source"), {
        target: { value: "smart" },
      });

      expect(
        await screen.findByText(/Plex smart collections automatically evaluate filter rules/i),
      ).toBeInTheDocument();
      expect(screen.getByLabelText(/Smart sort order/i)).toHaveValue("release.desc");

      const limitInput = screen.getByLabelText(/Item limit/i);
      await fireEvent.input(limitInput, { target: { value: "25" } });

      const labelInput = screen.getByLabelText(/Managed Plex label/i);
      await fireEvent.input(labelInput, { target: { value: "Marvel Universe" } });
    });

    it("configures seasonal window and summary template override", async () => {
      mockFetchRoutes({
        "/api/collections/groups": [],
        "/api/collections/12": { ...detail, rule },
      });
      goToCollectionView(detail, "configure");
      renderWithQueryClient(CollectionPage);

      const startInput = await screen.findByLabelText(/^Active start \(MM-DD\)/i);
      await fireEvent.input(startInput, { target: { value: "12-15" } });

      const endInput = screen.getByLabelText(/^Active end \(MM-DD\)/i);
      await fireEvent.input(endInput, { target: { value: "01-05" } });

      const templateInput = screen.getByLabelText(/^Summary template/i);
      await fireEvent.input(templateInput, { target: { value: "{title} seasonal" } });
    });

    it("switches to multi-source composite builders and adds builder items", async () => {
      mockFetchRoutes({
        "/api/collections/groups": [],
        "/api/collections/12": { ...detail, rule },
      });
      goToCollectionView(detail, "configure");
      renderWithQueryClient(CollectionPage);

      await fireEvent.change(await screen.findByLabelText("Source"), {
        target: { value: "builders" },
      });

      const addBtn = await screen.findByRole("button", { name: "MDBList" });
      await fireEvent.click(addBtn);
    });

    it("saves collection options with seasonal dates, summary format, and Plex visibility", async () => {
      let putBody: unknown = null;
      mockFetchRoutes({
        "/api/collections/groups": [],
        "/api/library/libraries": [{ id: "movies", title: "Movies", count: 1 }],
        "/api/library/items": { items: members, total: 1 },
        "/api/collections/12": ({ init }: { init: RequestInit }) => {
          if (init.method === "PUT") {
            putBody = JSON.parse(init.body as string);
            return Response.json({ ...detail, ...JSON.parse(init.body as string) });
          }
          return Response.json({ ...detail, rule });
        },
      });
      goToCollectionView(detail, "configure");
      renderWithQueryClient(CollectionPage);

      const displaySection = await screen.findByRole("region", { name: "Collection display" });
      const display = within(displaySection);

      const summaryFormatInput = display.getByLabelText(/^Summary template/i);
      await fireEvent.input(summaryFormatInput, { target: { value: "{title} - {group}" } });

      const schedule = within(screen.getByRole("region", { name: "Collection schedule" }));
      const startInput = schedule.getByLabelText(/^Active start/i);
      await fireEvent.input(startInput, { target: { value: "12-15" } });

      const endInput = schedule.getByLabelText(/^Active end/i);
      await fireEvent.input(endInput, { target: { value: "01-05" } });

      const visibleShared = display.getByLabelText(/Visible to shared users/i);
      await fireEvent.click(visibleShared);

      const visibleLibrary = display.getByLabelText(/Visible in library recommended/i);
      await fireEvent.click(visibleLibrary);

      const filterSelect = display.getByLabelText(/Collection filtering/i);
      await fireEvent.change(filterSelect, { target: { value: "admin" } });

      await fireEvent.click(screen.getByRole("button", { name: "Save Changes" }));

      await waitFor(() => expect(putBody).not.toBeNull());
      expect(putBody).toMatchObject({
        summary_format: "{title} - {group}",
        active_start_mmdd: "12-15",
        active_end_mmdd: "01-05",
        visible_shared: true,
        visible_library: true,
        collection_filtering: "admin",
      });
    });
  });
});
