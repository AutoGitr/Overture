import { fireEvent, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import CollectionMembers from "../../../lib/components/CollectionMembers.svelte";
import type { CollectionEditor } from "../../../lib/utils/collectionForms.svelte";
import { collectionDetail, mediaItem } from "../../helpers/fixtures";
import { renderWithQueryClient } from "../../helpers/render";

describe("CollectionMembers", () => {
  it("groups members by library as the libraries are listed: movies, then shows", async () => {
    // The libraries come movies first, then by title, as the server lists them.
    const libraries = [
      { id: "a", title: "Anime Films", media_type: "movie" as const, count: 1 },
      { id: "m", title: "Movies", media_type: "movie" as const, count: 1 },
      { id: "s", title: "Series", media_type: "show" as const, count: 1 },
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
});
