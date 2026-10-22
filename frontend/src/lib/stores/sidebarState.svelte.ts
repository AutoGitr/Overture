import type { SidebarTab } from "../utils/sidebarDomain";

/** A row auto-advance can move to: a stored item, or a TMDB title not yet stored. */
export type AdvanceEntry =
  | { kind: "item"; id: number }
  | { kind: "tmdb"; tmdb_id: number; title: string; media_type: SidebarTab };

export const sidebarState = $state<{
  /**
   * The complete rendered library result set, including rows outside the
   * virtual viewport. "Current sidebar items" operations act on it.
   */
  current: { type: SidebarTab; itemIds: number[] } | null;
  /** The TMDB results shown, in order, while the sidebar searches TMDB. */
  tmdbResults: AdvanceEntry[] | null;
}>({ current: null, tmdbResults: null });

/** The rows auto-advance moves through: the TMDB results, else the library's. */
export function advanceOrder(): AdvanceEntry[] {
  return (
    sidebarState.tmdbResults ??
    (sidebarState.current?.itemIds ?? []).map((id) => ({ kind: "item" as const, id }))
  );
}
