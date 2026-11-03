import { createQuery } from "@tanstack/svelte-query";
import { SvelteSet } from "svelte/reactivity";
import { getFolderRootsOptions } from "../../generated/rest/@tanstack/svelte-query.gen";
import type { ScanRequest } from "../../generated/rest/types.gen";
import { sidebarState } from "../stores/sidebarState.svelte";
import { persistedState } from "./persistedState.svelte";
import { toggleSelectedValue } from "./popupSelection";

export type FolderScope = ReturnType<typeof createFolderScope>;

/** The folders part of every folder-based job request. */
type FolderScopeRequest = Pick<ScanRequest, "item_ids" | "movie_folders" | "show_folders">;

/**
 * The media folders a folder-based job visits: the chosen library roots, or
 * the items the sidebar lists. The roots are read while the tab is shown,
 * and the choice is remembered under *prefix*. Create it during component
 * initialisation.
 */
export function createFolderScope(prefix: string, isActive: () => boolean) {
  const stored = persistedState(prefix, {
    selectedMovieFolders: [] as string[],
    selectedShowFolders: [] as string[],
    useSidebarItems: false,
  });
  const query = createQuery(() => ({ ...getFolderRootsOptions(), enabled: isActive() }));
  const folders = $derived(query.data ?? { movies: [], shows: [] });
  const movieRoots = $derived<ReadonlySet<string>>(new SvelteSet(folders.movies));
  const showRoots = $derived<ReadonlySet<string>>(new SvelteSet(folders.shows));
  // A remembered root the server no longer lists is never selected.
  const movieFolders = $derived(
    stored.selectedMovieFolders.filter((folder) => movieRoots.has(folder)),
  );
  const showFolders = $derived(
    stored.selectedShowFolders.filter((folder) => showRoots.has(folder)),
  );
  const sidebarItems = $derived(stored.useSidebarItems ? sidebarState.current : null);

  return {
    query,
    get folders() {
      return folders;
    },
    get movieFolders() {
      return movieFolders;
    },
    get showFolders() {
      return showFolders;
    },
    get useSidebarItems() {
      return stored.useSidebarItems;
    },
    set useSidebarItems(value: boolean) {
      stored.useSidebarItems = value;
    },
    /** Whether the scope holds anything to visit. */
    get hasSelection(): boolean {
      return stored.useSidebarItems
        ? !!sidebarItems?.itemIds.length
        : movieFolders.length + showFolders.length > 0;
    },
    /** Whether the scope reaches shows, which alone have season artwork. */
    get hasShows(): boolean {
      return stored.useSidebarItems ? sidebarItems?.type === "show" : showFolders.length > 0;
    },
    /** Whether the roots a selection names are known, so it can be sent. */
    get ready(): boolean {
      return stored.useSidebarItems || query.isSuccess;
    },
    toggle(folder: string, type: "movie" | "show") {
      stored.useSidebarItems = false;
      if (type === "movie") {
        stored.selectedMovieFolders = toggleSelectedValue(movieFolders, folder);
      } else {
        stored.selectedShowFolders = toggleSelectedValue(showFolders, folder);
      }
    },
    toggleAll(checked: boolean) {
      stored.useSidebarItems = false;
      stored.selectedMovieFolders = checked ? [...folders.movies] : [];
      stored.selectedShowFolders = checked ? [...folders.shows] : [];
    },
    /** The scope as a job request names it; remembers the choice. */
    request(): FolderScopeRequest {
      stored.save();
      return stored.useSidebarItems
        ? { item_ids: [...(sidebarItems?.itemIds ?? [])] }
        : { movie_folders: movieFolders, show_folders: showFolders };
    },
  };
}
