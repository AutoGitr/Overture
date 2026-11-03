import { SvelteMap } from "svelte/reactivity";
import { readJson, writeJson } from "../utils/storage";

const STORAGE_KEY = "sections_open";

/**
 * Which collapsible sections the user opened or closed, by title.
 *
 * The choice outlives the component: a section remounted by navigation, a
 * refetch or a keyed block, or given a new default, keeps it.
 */
class SectionState {
  readonly #open = new SvelteMap<string, boolean>(
    Object.entries(readJson<Record<string, boolean>>(STORAGE_KEY, {})),
  );

  /** Whether *title* is open; *fallback* until the user has chosen. */
  isOpen(title: string, fallback: boolean): boolean {
    return this.#open.get(title) ?? fallback;
  }

  setOpen(title: string, open: boolean) {
    this.#open.set(title, open);
    writeJson(STORAGE_KEY, Object.fromEntries(this.#open));
  }

  /** Forget every choice, as on a fresh browser. */
  reset() {
    this.#open.clear();
  }
}

export const sectionState = new SectionState();
