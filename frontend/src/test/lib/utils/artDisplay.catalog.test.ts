import { describe, expect, it } from "vitest";
import { catalogLocalArtUrl } from "../../../lib/utils/artDisplay";
import { catalogRow } from "../../helpers/fixtures";

const POSTER = "https://image.tmdb.org/t/p/original/heat.jpg";
const HASH = "a".repeat(64);

describe("catalogLocalArtUrl", () => {
  it("shows the library's local file of a catalog link, without fetching the link", () => {
    expect(
      catalogLocalArtUrl(
        catalogRow({ library_item_id: 4, local_art: { [POSTER]: HASH } }),
        POSTER,
        "poster",
      ),
    ).toBe(`/api/library/items/4/local-image/poster?t=${HASH}&size=display`);
    expect(
      catalogLocalArtUrl(
        catalogRow({ library_collection_id: 9, local_art: { [POSTER]: HASH } }),
        POSTER,
        "poster",
      ),
    ).toBe(`/api/collections/9/local-image/poster?t=${HASH}&size=display`);
  });

  it("leaves a link the library holds no file of to be fetched", () => {
    expect(catalogLocalArtUrl(catalogRow({ library_item_id: 4 }), POSTER, "poster")).toBeNull();
    expect(catalogLocalArtUrl(catalogRow({ library_item_id: 4 }), null, "background")).toBeNull();
  });
});
