import type { MediaItemRead } from "../../generated/rest/types.gen";
import type { CatalogContext } from "./catalogDraft";
import { upsertLibraryItem } from "../rest/cache";
import { beginAutoAdvance, handleFirstSelectionAdvance, type FirstSelection } from "./autoAdvance";

/** The artwork slot a panel saves into: of a stored item, or of a TMDB title. */
export type ArtSlotTarget =
  | {
      kind: "catalog";
      catalog: CatalogContext;
      seasonNum: number | null;
    }
  | { kind: "item"; itemId: number; seasonId: number | null }
  | {
      kind: "tmdb";
      mediaType: MediaItemRead["media_type"];
      tmdbId: number;
      seasonNum: number | null;
    };

export type CollectionArtTarget = {
  kind: "collection";
  collectionId: number;
  tmdbId: number | null;
  mediaType: MediaItemRead["media_type"];
};

/**
 * Show the item a TMDB title's first selection stored: in the library at
 * once, and in the detail view as auto-advance decides. Nothing moves if the
 * user has navigated away meanwhile.
 */
export async function openPersistedItem(
  item: MediaItemRead,
  selection: FirstSelection,
  context: ReturnType<typeof beginAutoAdvance>,
): Promise<void> {
  upsertLibraryItem(item);
  await handleFirstSelectionAdvance(item, selection, context);
}
