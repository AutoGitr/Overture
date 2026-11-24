import type { AdvanceRecord } from "../utils/recordAdvance";
import type { SidebarTab } from "../utils/sidebarShared";

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

/** What the mounted sidebar lists, as it lists it. */
export interface SidebarListed {
  /**
   * What the list shows and in which order: its scope, sort, filters and
   * search. Auto-advance starts its walk again when it changes.
   */
  readonly view: string;
  /** The library titles listed, including rows outside the virtual viewport. */
  readonly current: { type: SidebarTab; itemIds: number[] } | null;
  readonly listedCollections: { type: SidebarTab; collectionIds: number[] } | null;
  /** The collections or catalog entries listed, in order. */
  readonly records: AdvanceRecord[] | null;
}

/** What the sidebar's TMDB search shows, in order. */
export interface SidebarSearched {
  readonly results: AdvanceEntry[];
  /** The results that open as a collection or catalog entry. */
  readonly records: AdvanceRecord[];
}

/**
 * The sidebar's lists as other views read them. The sidebar and its TMDB
 * search show theirs here while mounted; every value is read from them live.
 */
class SidebarState {
  listed = $state.raw<SidebarListed | null>(null);
  searched = $state.raw<SidebarSearched | null>(null);
  /** The order auto-advance goes through, kept from when it reached the open row. */
  walk = $state<AdvanceWalk | null>(null);

  get view() {
    return this.listed?.view ?? null;
  }
  /** "Current sidebar items" operations act on these titles. */
  get current() {
    return this.listed?.current ?? null;
  }
  get collections() {
    return this.listed?.listedCollections ?? null;
  }
  get records() {
    return this.listed?.records ?? null;
  }
  get tmdbResults() {
    return this.searched?.results ?? null;
  }
  get tmdbRecords() {
    return this.searched?.records ?? null;
  }

  /** Show *listed* until the returned cleanup, as an effect returns it, runs. */
  show(listed: SidebarListed) {
    this.listed = listed;
    return () => {
      if (this.listed === listed) this.listed = null;
    };
  }

  /** Show *searched* until the returned cleanup runs. */
  search(searched: SidebarSearched) {
    this.searched = searched;
    return () => {
      if (this.searched === searched) this.searched = null;
    };
  }
}

export const sidebarState = new SidebarState();

/** The rows auto-advance moves through: the TMDB results, else the library's. */
export function advanceOrder(): AdvanceEntry[] {
  return (
    sidebarState.tmdbResults ??
    (sidebarState.current?.itemIds ?? []).map((id) => ({ kind: "item" as const, id }))
  );
}

/** The collections or catalog entries auto-advance moves through: the TMDB results', else the list's. */
export function advanceRecords(): AdvanceRecord[] {
  return sidebarState.tmdbRecords ?? sidebarState.records ?? [];
}
