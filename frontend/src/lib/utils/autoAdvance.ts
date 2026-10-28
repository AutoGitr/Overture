import { getSeasonsOptions } from "../../generated/rest/@tanstack/svelte-query.gen";
import type {
  AppSettingsRead,
  ArtType,
  MediaItemRead,
  SeasonRead,
} from "../../generated/rest/types.gen";
import { findCachedLibraryItem } from "../rest/cache";
import { queryClient } from "../rest/queryClient";
import {
  goToItemArt,
  goToItemThemes,
  goToItemView,
  goToSeason,
  route,
  routedItemId,
  routedItemView,
} from "../router/routes";
import { settingsState } from "../stores/settingsState.svelte";
import { advanceOrder, type AdvanceEntry } from "../stores/sidebarState.svelte";
import { itemDetailImageUrls } from "./artDisplay";
import { preloadImages } from "./imagePreload";

export type AutoAdvanceSettings = Pick<
  AppSettingsRead,
  "workflow" | "auto_advance" | "auto_advance_skip_completed"
>;

export type NavigationTarget =
  | { type: "art"; subtab: "poster" | "background" }
  | { type: "season"; season: SeasonRead }
  | { type: "theme" }
  | { type: "next_item" }
  | null;

function getNavigableSeasons(seasons: SeasonRead[]): SeasonRead[] {
  return [...seasons].sort((a, b) => a.season_num - b.season_num);
}

/**
 * Determine the next navigation target after selecting an artwork candidate.
 */
export function computeNextArtworkTarget(options: {
  item: MediaItemRead;
  artType: ArtType;
  seasonId: number | null;
  seasons: SeasonRead[];
  settings: AutoAdvanceSettings;
}): NavigationTarget {
  const { item, artType, seasonId, seasons, settings } = options;

  if (settings.auto_advance === "off" || settings.workflow === "themes") return null;

  if (artType === "poster") {
    if (!settings.auto_advance_skip_completed || item.background_status !== "complete") {
      return { type: "art", subtab: "background" };
    }
  }

  let remainingSeasons = item.media_type === "show" ? getNavigableSeasons(seasons) : [];
  if (artType === "season_poster") {
    const index = remainingSeasons.findIndex((season) => season.id === seasonId);
    if (index === -1) return null;
    remainingSeasons = remainingSeasons.slice(index + 1);
  }
  const nextSeason = remainingSeasons.find(
    (season) => !settings.auto_advance_skip_completed || season.poster_status !== "complete",
  );
  if (nextSeason) {
    return { type: "season", season: nextSeason };
  }

  if (
    settings.workflow === "art_and_themes" &&
    (!settings.auto_advance_skip_completed || item.theme_status !== "complete")
  ) {
    return { type: "theme" };
  }
  return settings.auto_advance === "slots_and_items" ? { type: "next_item" } : null;
}

/** The first selection of a TMDB title: an artwork slot, or its theme. */
export type FirstSelection = { artType: ArtType; seasonNum: number | null } | { theme: true };

/**
 * Determine the next navigation target after selecting a theme song.
 */
export function computeNextThemeTarget(settings: AutoAdvanceSettings): NavigationTarget {
  // The theme is an item's last slot, so only the item mode moves on from it.
  if (settings.auto_advance === "slots_and_items" && settings.workflow !== "art") {
    return { type: "next_item" };
  }
  return null;
}

function executeAutoAdvanceTarget(
  target: NavigationTarget,
  currentItem: MediaItemRead,
  settings: AutoAdvanceSettings,
  order: readonly AdvanceEntry[],
): void {
  if (!target) return;
  switch (target.type) {
    case "art":
      goToItemArt(currentItem, target.subtab);
      break;
    case "season":
      goToSeason(currentItem, target.season);
      break;
    case "theme":
      goToItemThemes(currentItem);
      break;
    case "next_item":
      advanceToNextItem(currentItem, settings, order);
      break;
  }
}

/** Whether a sidebar row is the item, including as the TMDB title it was stored from. */
function isEntryFor(entry: AdvanceEntry, item: MediaItemRead): boolean {
  return entry.kind === "item"
    ? entry.id === item.id
    : entry.tmdb_id === item.tmdb_id && entry.media_type === item.media_type;
}

/** The entry auto-advance moves on to from *currentItem*, with its cached item if stored. */
function nextAdvanceEntry(
  currentItem: MediaItemRead,
  settings: AutoAdvanceSettings,
  order: readonly AdvanceEntry[],
): { entry: AdvanceEntry; candidate: MediaItemRead | undefined } | null {
  const currentIdx = order.findIndex((entry) => isEntryFor(entry, currentItem));
  if (currentIdx === -1) return null;

  const themesOnly = settings.workflow === "themes";
  for (const entry of order.slice(currentIdx + 1)) {
    // A TMDB title not yet stored has nothing chosen, so it is never complete.
    if (entry.kind === "tmdb") return { entry, candidate: undefined };
    const candidate = findCachedLibraryItem(entry.id);
    if (candidate && settings.auto_advance_skip_completed) {
      const themeComplete = candidate.theme_status === "complete";
      const complete = themesOnly
        ? themeComplete
        : candidate.art_status === "complete" && (settings.workflow === "art" || themeComplete);
      if (complete) continue;
    }
    return { entry, candidate };
  }
  return null;
}

/**
 * Fetch the detail images of the item auto-advance would open next, so they
 * show at once when it does.
 */
export function preloadNextItem(currentItem: MediaItemRead, settings: AutoAdvanceSettings): void {
  if (settings.auto_advance !== "slots_and_items") return;
  const next = nextAdvanceEntry(currentItem, settings, advanceOrder());
  if (next?.candidate) {
    preloadImages(itemDetailImageUrls(next.candidate, settingsState.show_background_image), "next");
  }
}

/** Use the list from selection time: saving can remove or reorder a filtered row. */
export function advanceToNextItem(
  currentItem: MediaItemRead,
  settings: AutoAdvanceSettings,
  order: readonly AdvanceEntry[] = advanceOrder(),
): boolean {
  const next = nextAdvanceEntry(currentItem, settings, order);
  if (!next) return false;
  const { entry, candidate } = next;
  const themesOnly = settings.workflow === "themes";
  if (entry.kind === "tmdb") {
    if (themesOnly) goToItemThemes(entry);
    else goToItemArt(entry, "poster");
    return true;
  }
  const nextItem = candidate ?? {
    id: entry.id,
    title: "",
    media_type: currentItem.media_type,
  };
  if (themesOnly) {
    goToItemThemes(nextItem);
  } else if (!candidate || !settings.auto_advance_skip_completed) {
    goToItemArt(nextItem, "poster");
  } else if (candidate.poster_status !== "complete") {
    goToItemArt(candidate, "poster");
  } else if (candidate.background_status !== "complete") {
    goToItemArt(candidate, "background");
  } else if (candidate.media_type === "show" && candidate.season_posters_status !== "complete") {
    goToItemArt(candidate, "seasons");
  } else if (settings.workflow === "art_and_themes") {
    goToItemThemes(candidate);
  } else {
    goToItemArt(candidate, "poster");
  }
  return true;
}

/** How long a saved selection shows before auto-advance moves on. */
export const AUTO_ADVANCE_DELAY_MS = 300;

let pendingAdvanceTimer: ReturnType<typeof setTimeout> | null = null;
let advanceGeneration = 0;

type AutoAdvanceContext = {
  generation: number;
  itemId: number | null;
  pathname: string;
  order: AdvanceEntry[];
};

export function cancelPendingAutoAdvance(): void {
  advanceGeneration++;
  if (pendingAdvanceTimer !== null) clearTimeout(pendingAdvanceTimer);
  pendingAdvanceTimer = null;
}

/** Capture before the request so late responses cannot take over a newer selection. */
export function beginAutoAdvance(): AutoAdvanceContext {
  cancelPendingAutoAdvance();
  return {
    generation: advanceGeneration,
    itemId: routedItemId(),
    pathname: route.pathname,
    order: [...advanceOrder()],
  };
}

function isCurrent(context: AutoAdvanceContext): boolean {
  return context.generation === advanceGeneration && context.pathname === route.pathname;
}

export function scheduleAutoAdvance(
  action: () => void,
  context: AutoAdvanceContext,
  delayMs: number,
): void {
  if (!isCurrent(context)) return;
  if (pendingAdvanceTimer !== null) clearTimeout(pendingAdvanceTimer);
  const advance = () => {
    pendingAdvanceTimer = null;
    if (isCurrent(context)) action();
  };
  if (delayMs <= 0) advance();
  else pendingAdvanceTimer = setTimeout(advance, delayMs);
}

export async function handleArtworkSelectionAdvance(options: {
  item: MediaItemRead;
  artType: ArtType;
  seasonId: number | null;
  context: AutoAdvanceContext;
}): Promise<void> {
  const { item, context } = options;
  if (!isCurrent(context) || item.id !== context.itemId) return;
  // A snapshot: loading settings replaces the object rather than changing it.
  const settings = settingsState.current;
  if (settings.auto_advance === "off" || settings.workflow === "themes") return;

  // An unfulfilled seasons query is not an empty show. Wait before resolving its next slot.
  const seasons =
    item.media_type === "show"
      ? await queryClient.fetchQuery(getSeasonsOptions({ path: { item_id: item.id } }))
      : [];
  const target = computeNextArtworkTarget({ ...options, seasons, settings });
  if (target) {
    scheduleAutoAdvance(
      () => executeAutoAdvanceTarget(target, item, settings, context.order),
      context,
      AUTO_ADVANCE_DELAY_MS,
    );
  }
}

export function handleThemeSelectionAdvance(
  item: MediaItemRead,
  context: AutoAdvanceContext,
): void {
  if (!isCurrent(context) || item.id !== context.itemId) return;
  // A snapshot: loading settings replaces the object rather than changing it.
  const settings = settingsState.current;
  const target = computeNextThemeTarget(settings);
  if (target) {
    scheduleAutoAdvance(
      () => executeAutoAdvanceTarget(target, item, settings, context.order),
      context,
      AUTO_ADVANCE_DELAY_MS,
    );
  }
}

/** Where auto-advance goes after the first selection of a TMDB title. */
async function firstSelectionTarget(
  item: MediaItemRead,
  selection: FirstSelection,
  settings: AutoAdvanceSettings,
): Promise<NavigationTarget> {
  if ("theme" in selection) return computeNextThemeTarget(settings);
  if (settings.auto_advance === "off" || settings.workflow === "themes") return null;
  const seasons =
    item.media_type === "show"
      ? await queryClient.fetchQuery(getSeasonsOptions({ path: { item_id: item.id } }))
      : [];
  return computeNextArtworkTarget({
    item,
    artType: selection.artType,
    seasonId: seasons.find((season) => season.season_num === selection.seasonNum)?.id ?? null,
    seasons,
    settings,
  });
}

/**
 * Leave a TMDB title for the item its first selection stored, then advance as
 * after any other selection: same settings, targets, delay and next item.
 *
 * The item replaces the title's history entry, so Back never returns to a
 * title that is now stored; the advance then adds an entry as usual. Without
 * a target the item opens at once in the same view.
 */
export async function handleFirstSelectionAdvance(
  item: MediaItemRead,
  selection: FirstSelection,
  context: AutoAdvanceContext,
): Promise<void> {
  // A snapshot: loading settings replaces the object rather than changing it.
  const settings = settingsState.current;
  // A failed season lookup costs only the advance, never the switch to the item.
  const target = await firstSelectionTarget(item, selection, settings).catch(() => null);
  scheduleAutoAdvance(
    () => {
      goToItemView(item, routedItemView(), { replace: true });
      executeAutoAdvanceTarget(target, item, settings, context.order);
    },
    context,
    target ? AUTO_ADVANCE_DELAY_MS : 0,
  );
}
