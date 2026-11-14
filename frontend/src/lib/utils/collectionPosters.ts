import type { CollectionPosterStyle } from "../../generated/rest/types.gen";
import { keysOf } from "./records";

/** How each style of OvertureDB collection poster is named. */
export const COLLECTION_POSTER_LABELS: Record<CollectionPosterStyle, string> = {
  individual: "Individual",
  matte: "Matte",
  overlay: "Overlay",
};
export const COLLECTION_POSTER_STYLES = keysOf(COLLECTION_POSTER_LABELS);

/** The catalog entry field that holds a collection's poster of *style*. */
export function collectionPosterField(style: CollectionPosterStyle) {
  return `poster_url_${style}` as const;
}
