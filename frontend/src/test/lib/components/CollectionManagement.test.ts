import { fireEvent, screen, waitFor } from "@testing-library/svelte";
import { beforeEach, describe, expect, it } from "vitest";
import CollectionPage from "../../../lib/router/pages/CollectionPage.svelte";
import NewCollectionModal from "../../../lib/components/NewCollectionModal.svelte";
import CollectionGeneratorModal from "../../../lib/components/CollectionGeneratorModal.svelte";
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
import { appSettings, collectionDetail, mediaItem } from "../../helpers/fixtures";
import { renderWithQueryClient } from "../../helpers/render";
import type { CollectionRuleRead } from "../../../generated/rest/types.gen";

const members = [
  mediaItem({ id: 1, title: "First", library_id: "movies", server_item_id: "m1" }),
  mediaItem({ id: 2, title: "Second", library_id: "movies", server_item_id: "m2" }),
];
const detail = collectionDetail({
  id: 12,
  title: "Saga",
  library_id: "movies",
  members,
  child_count: 2,
});
const rule: CollectionRuleRead = {
  source_type: "mdblist",
  source_identifier: "user/list",
  filters: { decade: null, studio: null, genre: null },
  sync_mode: null,
  minimum_items: null,
  delete_below_minimum: null,
  sync_interval_hours: 24,
  enabled: true,
  last_error: null,
  last_synced_at: null,
};

describe("collection management", () => {
  beforeEach(async () => {
    queryClient.clear();
    settingsState.load(appSettings({ media_server: "plex", collections_supported: true }));
    await navigate("/movies/collections/:collectionSlug", {
      params: { collectionSlug: "12-saga" },
    });
  });

  it("removes members through the API and keeps the collection view in sync", async () => {
    const { calls } = mockFetchRoutes({
      "/api/collections/12": detail,
      "/api/library/items": { items: members, total: 2 },
      "/api/collections/12/members": { ...detail, members: [members[1]], child_count: 1 },
    });
    renderWithQueryClient(CollectionPage);
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
      "/api/collections/12": ({ init }: { init: RequestInit }) => {
        if (init.method === "PUT") {
          saved = true;
          return Response.json({ ...detail, title: "New saga" });
        }
        return Response.json(detail);
      },
    });
    goToCollectionView(detail, "settings");
    renderWithQueryClient(CollectionPage);
    await fireEvent.input(await screen.findByLabelText("Title"), { target: { value: "New saga" } });
    await fireEvent.click(screen.getByRole("button", { name: "Save collection settings" }));
    await waitFor(() => expect(saved).toBe(true));
    expect(await screen.findByRole("heading", { name: "New saga" })).toBeInTheDocument();
  });

  it("saves rule overrides and runs a saved rule", async () => {
    const { calls } = mockFetchRoutes({
      "/api/collections/12": { ...detail, rule },
      "/api/collections/12/rule": rule,
      "/api/collections/12/sync": { added: 1, removed: 0, skipped: false, deleted: false },
    });
    goToCollectionView(detail, "rule");
    renderWithQueryClient(CollectionPage);
    await fireEvent.change(await screen.findByLabelText("Sync strategy"), {
      target: { value: "append" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Save rule" }));
    await waitFor(() => expect(calls.some((call) => call.init.method === "PUT")).toBe(true));
    const body = JSON.parse(String(calls.find((call) => call.init.method === "PUT")?.init.body));
    expect(body.sync_mode).toBe("append");
    expect(body.minimum_items).toBeNull();
    await fireEvent.click(screen.getByRole("button", { name: "Sync now" }));
    await waitFor(() =>
      expect(calls.some((call) => call.url.includes("/sync") && call.init.method === "POST")).toBe(
        true,
      ),
    );
  });

  it("creates a collection with selected library members", async () => {
    const { calls } = mockFetchRoutes({
      "/api/library/libraries": [{ id: "movies", title: "Movies", count: 2 }],
      "/api/library/items": { items: members, total: 2 },
      "/api/collections": detail,
    });
    renderWithQueryClient(NewCollectionModal);
    await fireEvent.input(screen.getByLabelText("Title"), { target: { value: "Saga" } });
    await screen.findByRole("option", { name: "Movies" });
    await fireEvent.change(screen.getByLabelText("Library"), { target: { value: "movies" } });
    await fireEvent.click(await screen.findByRole("checkbox", { name: "First" }));
    await fireEvent.click(screen.getByRole("button", { name: "Create collection (1 members)" }));
    await waitFor(() => expect(route.pathname).toBe("/movies/collections/12-saga"));
    expect(
      JSON.parse(String(calls.find((call) => call.init.method === "POST")?.init.body)),
    ).toMatchObject({ title: "Saga", library_id: "movies", member_ids: [1] });
  });

  it("previews presets before generating only selected collections", async () => {
    const { calls } = mockFetchRoutes({
      "/api/library/libraries": [{ id: "movies", title: "Movies", count: 2 }],
      "/api/collections/generator/preview": [
        { title: "1990s", count: 2, filters: { decade: 1990, studio: null, genre: null } },
      ],
      "/api/collections/generator/apply": { created: [12], errors: {} },
    });
    renderWithQueryClient(CollectionGeneratorModal);
    await screen.findByRole("option", { name: "Movies" });
    await fireEvent.change(screen.getByLabelText("Library"), { target: { value: "movies" } });
    await fireEvent.click(screen.getByRole("button", { name: "Preview collections" }));
    await fireEvent.click(await screen.findByRole("checkbox", { name: "1990s (2 members)" }));
    await fireEvent.click(screen.getByRole("button", { name: "Generate selected collections" }));
    await waitFor(() => expect(calls.some((call) => call.url.endsWith("/apply"))).toBe(true));
    expect(
      JSON.parse(String(calls.find((call) => call.url.endsWith("/apply"))?.init.body)),
    ).toMatchObject({ titles: ["1990s"], preset: "decades" });
  });

  it("round-trips collection art, rule, theme and settings views in both libraries", async () => {
    for (const media_type of ["movie", "show"] as const) {
      const target = { ...detail, media_type };
      for (const view of ["members", "art", "themes", "rule", "settings"] as const) {
        goToCollectionView(target, view, "background");
        await waitFor(() => expect(routedCollectionView()).toBe(view));
        expect(routedCollectionId()).toBe(12);
        if (view === "art") expect(routedCollectionArtType()).toBe("background");
      }
    }
  });
});
