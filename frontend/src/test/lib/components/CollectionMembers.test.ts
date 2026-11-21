import { fireEvent, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it } from "vitest";
import CollectionMembers from "../../../lib/components/CollectionMembers.svelte";
import { settingsState } from "../../../lib/stores/settingsState.svelte";
import type { CollectionEditor } from "../../../lib/utils/collectionEditor.svelte";
import { appSettings, collectionDetail, mediaItem, mediaServers } from "../../helpers/fixtures";
import { renderWithQueryClient } from "../../helpers/render";

describe("CollectionMembers", () => {
  afterEach(() => settingsState.reset());

  it("groups members by library as the libraries are listed: movies, then shows", async () => {
    settingsState.load(appSettings());
    // The libraries come movies first, then by title, as the server lists them.
    const libraries = [
      { id: "a", title: "Anime Films", media_type: "movie" as const, server_id: 1, count: 1 },
      { id: "m", title: "Movies", media_type: "movie" as const, server_id: 1, count: 1 },
      { id: "s", title: "Series", media_type: "show" as const, server_id: 1, count: 1 },
    ];
    const items = [
      mediaItem({ id: 1, title: "Show", media_type: "show", library_id: "s" }),
      mediaItem({ id: 2, title: "Film", library_id: "m" }),
      mediaItem({ id: 3, title: "Anime", library_id: "a" }),
    ];
    // The collection names its libraries and members in another order.
    const editor = {
      collection: collectionDetail({
        member_ids: [1, 2, 3],
        library_ids: ["s", "m", "a"],
        child_count: 3,
      }),
      manualMembersAllowed: false,
      availableMembers: () => [],
      busy: false,
    } as unknown as CollectionEditor;

    renderWithQueryClient(CollectionMembers, { editor, libraryItems: items, libraries });
    await fireEvent.click(screen.getByRole("button", { name: /^Members/ }));

    expect(
      screen
        .getAllByRole("region", { name: / members$/ })
        .map((group) => group.getAttribute("aria-label"))
        .filter((label) => label !== "Collection members"),
    ).toEqual(["Anime Films members", "Movies members", "Series members"]);
  });

  it("heads each server's libraries with its name when several servers are configured", async () => {
    settingsState.load(appSettings({ media_servers: mediaServers("plex", "jellyfin") }));
    const libraries = [
      { id: "p", title: "Movies", media_type: "movie" as const, server_id: 1, count: 1 },
      { id: "j", title: "Movies", media_type: "movie" as const, server_id: 2, count: 1 },
    ];
    const editor = {
      collection: collectionDetail({ member_ids: [1, 2], library_ids: ["j", "p"], child_count: 2 }),
      manualMembersAllowed: false,
      availableMembers: () => [],
      busy: false,
    } as unknown as CollectionEditor;
    const items = [
      mediaItem({ id: 1, title: "Jelly film", library_id: "j" }),
      mediaItem({ id: 2, title: "Plex film", library_id: "p" }),
    ];

    renderWithQueryClient(CollectionMembers, { editor, libraryItems: items, libraries });
    await fireEvent.click(screen.getByRole("button", { name: /^Members/ }));

    expect(screen.getAllByRole("heading", { level: 4 }).map((h) => h.textContent)).toEqual([
      "Plex",
      "Movies",
      "Jellyfin",
      "Movies",
    ]);
    expect(screen.getByRole("region", { name: "Jellyfin · Movies members" })).toBeInTheDocument();
  });
});
