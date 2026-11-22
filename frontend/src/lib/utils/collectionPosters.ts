import { COLLECTION_POSTER_LABELS } from "../../generated/settings";
import type { CollectionPosterStyle } from "../../generated/rest/types.gen";
import { keysOf } from "./records";

export const COLLECTION_POSTER_STYLES = keysOf(COLLECTION_POSTER_LABELS);
/** Each style with its name, as a choice offers them. */
export const COLLECTION_POSTER_OPTIONS = COLLECTION_POSTER_STYLES.map(
  (style) => [style, COLLECTION_POSTER_LABELS[style]] as const,
);

/** The catalog entry field that holds a collection's poster of *style*. */
export function collectionPosterField(style: CollectionPosterStyle) {
  return `poster_url_${style}` as const;
}
