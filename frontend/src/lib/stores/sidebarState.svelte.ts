import type { AdvanceRecord } from "../utils/recordAdvance";
import type { SidebarTab } from "../utils/sidebarDomain";

/** A row auto-advance can move to: a stored item, or a TMDB title not yet stored. */
export type AdvanceEntry =
  | { kind: "item"; id: number }
  | { kind: "tmdb"; tmdb_id: number; title: string; media_type: SidebarTab };

/** The sidebar's rows as auto-advance walks them from the row at *key*. */
export interface AdvanceWalk {
  key: string | null;
  view: string | null;
  items: readonly AdvanceEntry[];
  records: readonly AdvanceRecord[];
}

export const sidebarState = $state<{
  /**
   * The complete rendered library result set, including rows outside the
   * virtual viewport. "Current sidebar items" operations act on it.
   */
  current: { type: SidebarTab; itemIds: number[] } | null;
  collections: { type: SidebarTab; collectionIds: number[] } | null;
  /** The TMDB results shown, in order, while the sidebar searches TMDB. */
  tmdbResults: AdvanceEntry[] | null;
  /** The collections or catalog entries shown, in order, for auto-advance. */
  records: AdvanceRecord[] | null;
  /**
   * What the list shows and in which order: its scope, sort, filters and
   * search. Auto-advance starts its walk again when it changes.
   */
  view: string | null;
  /** The order auto-advance goes through, kept from when it reached the open row. */
  walk: AdvanceWalk | null;
}>({
  current: null,
  collections: null,
  tmdbResults: null,
  records: null,
  view: null,
  walk: null,
});

/** The rows auto-advance moves through: the TMDB results, else the library's. */
export function advanceOrder(): AdvanceEntry[] {
  return (
    sidebarState.tmdbResults ??
    (sidebarState.current?.itemIds ?? []).map((id) => ({ kind: "item" as const, id }))
  );
}
