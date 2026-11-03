import type { CatalogEntryRow, CollectionRead } from "../../generated/rest/types.gen";
import { goToCatalogEntry, goToCollectionView, type ItemView } from "../router/routes";
import { settingsState } from "../stores/settingsState.svelte";
import { sidebarState } from "../stores/sidebarState.svelte";
import {
  AUTO_ADVANCE_DELAY_MS,
  beginAutoAdvance,
  isCurrent,
  scheduleAutoAdvance,
  type AutoAdvanceContext,
  type AutoAdvanceSettings,
} from "./autoAdvance";
import type { CatalogContext } from "./catalogDraft";

/**
 * A slot of a collection or catalog entry: its art, one season's poster (or
 * the seasons as a whole, before their list is known), or its theme.
 */
export type RecordSlot = "poster" | "background" | "seasons" | `season:${number}` | "theme";

/**
 * A collection or catalog entry as auto-advance sees it, which moves through
 * them as it does through items: the same settings, order, skips and delay.
 */
export interface AdvanceRecord {
  /** The same for its sidebar row and its page. */
  key: string;
  /** Its slots in the order they are visited, and which are complete. */
  slots: readonly { slot: RecordSlot; complete: boolean }[];
  open(slot: RecordSlot): void;
}

export type RecordAdvanceContext = AutoAdvanceContext & { records: AdvanceRecord[] };

function inWorkflow(slot: RecordSlot, workflow: AutoAdvanceSettings["workflow"]): boolean {
  return slot === "theme" ? workflow !== "art" : workflow !== "themes";
}

function shownSlots(record: AdvanceRecord, settings: AutoAdvanceSettings) {
  return record.slots.filter(({ slot }) => inWorkflow(slot, settings.workflow));
}

/** Where auto-advance goes after *current*: a slot, the next row, or nowhere. */
export function nextRecordTarget(
  record: AdvanceRecord,
  current: RecordSlot,
  settings: AutoAdvanceSettings,
): RecordSlot | "next" | null {
  if (settings.auto_advance === "off" || !inWorkflow(current, settings.workflow)) return null;
  const slots = shownSlots(record, settings);
  const index = slots.findIndex(({ slot }) => slot === current);
  if (index === -1) return null;
  const next = slots
    .slice(index + 1)
    .find(({ complete }) => !settings.auto_advance_skip_completed || !complete);
  if (next) return next.slot;
  return settings.auto_advance === "slots_and_items" ? "next" : null;
}

/** Open the row after *key*, at its first slot still to do when complete ones are skipped. */
export function openNextRecord(
  key: string,
  records: readonly AdvanceRecord[],
  settings: AutoAdvanceSettings,
): boolean {
  const index = records.findIndex((record) => record.key === key);
  if (index === -1) return false;
  const skip = settings.auto_advance_skip_completed;
  for (const record of records.slice(index + 1)) {
    const slots = shownSlots(record, settings);
    const first = slots.find(({ complete }) => !skip || !complete);
    if (!first) continue;
    record.open(first.slot);
    return true;
  }
  return false;
}

/** Capture before the save, with the rows the sidebar shows then. */
export function beginRecordAdvance(): RecordAdvanceContext {
  return { ...beginAutoAdvance(), records: [...(sidebarState.records ?? [])] };
}

/** After *current* of *key* was saved, move on as the settings say. */
export function handleRecordSelectionAdvance(
  key: string,
  current: RecordSlot,
  context: RecordAdvanceContext,
  /** The record as its page knows it, which is exact where its row is not. */
  page?: AdvanceRecord,
): void {
  if (!isCurrent(context)) return;
  const record = page ?? context.records.find((row) => row.key === key);
  if (!record) return;
  // A snapshot: loading settings replaces the object rather than changing it.
  const settings = settingsState.current;
  const saved = {
    ...record,
    slots: record.slots.map((entry) =>
      entry.slot === current ? { ...entry, complete: true } : entry,
    ),
  };
  const target = nextRecordTarget(saved, current, settings);
  if (!target) return;
  scheduleAutoAdvance(
    () =>
      target === "next" ? openNextRecord(key, context.records, settings) : record.open(target),
    context,
    AUTO_ADVANCE_DELAY_MS,
  );
}

export function collectionKey(id: number): string {
  return `collection:${id}`;
}

/** A library collection; Emby keeps no collection themes. */
export function collectionRecord(row: CollectionRead): AdvanceRecord {
  const themes = settingsState.current.media_server !== "emby";
  return {
    key: collectionKey(row.id),
    slots: [
      { slot: "poster", complete: row.poster_status === "complete" },
      { slot: "background", complete: row.background_status === "complete" },
      ...(themes ? [{ slot: "theme" as const, complete: row.theme_status === "complete" }] : []),
    ],
    open: (slot) =>
      goToCollectionView(
        row,
        slot === "theme" ? "themes" : "art",
        slot === "background" ? "background" : "poster",
      ),
  };
}

export function catalogKey(target: { media_type: string; entry_key: string }): string {
  return `catalog:${target.media_type}:${target.entry_key}`;
}

function catalogView(slot: RecordSlot): ItemView {
  if (slot === "theme") return { mode: "themes", artSubTab: "poster", drillSeasonNum: null };
  if (slot === "poster" || slot === "background")
    return { mode: "art", artSubTab: slot, drillSeasonNum: null };
  const season = slot === "seasons" ? null : Number(slot.slice("season:".length));
  return { mode: "art", artSubTab: "seasons", drillSeasonNum: season };
}

type CatalogSlots = Pick<
  CatalogEntryRow,
  "media_type" | "poster_url" | "background_url" | "youtube_id_overturedb" | "youtube_id_themerrdb"
> & { no_theme?: boolean | null };

function catalogRecord(
  target: { media_type: CatalogEntryRow["media_type"]; entry_key: string },
  entry: CatalogSlots,
  seasons: { slot: RecordSlot; complete: boolean }[],
): AdvanceRecord {
  return {
    key: catalogKey(target),
    slots: [
      { slot: "poster", complete: !!entry.poster_url },
      { slot: "background", complete: !!entry.background_url },
      ...seasons,
      {
        slot: "theme",
        complete: !!(entry.youtube_id_overturedb || entry.youtube_id_themerrdb || entry.no_theme),
      },
    ],
    open: (slot) => goToCatalogEntry(target, catalogView(slot)),
  };
}

/** A catalog row; its seasons are one slot until its page lists them. */
export function catalogRowRecord(row: CatalogEntryRow): AdvanceRecord {
  return catalogRecord(
    row,
    row,
    row.media_type === "show" ? [{ slot: "seasons", complete: row.season_posters > 0 }] : [],
  );
}

/** The open catalog entry, its draft included, with each season of a show. */
export function catalogPageRecord(catalog: CatalogContext): AdvanceRecord {
  const posters = new Set(
    (catalog.entry.seasons ?? [])
      .filter((season) => !!season.poster_url)
      .map((season) => season.season_num),
  );
  return catalogRecord(
    catalog.target,
    { ...catalog.entry, media_type: catalog.target.media_type },
    catalog.seasons.map(({ season_num }) => ({
      slot: `season:${season_num}` as const,
      complete: posters.has(season_num),
    })),
  );
}
