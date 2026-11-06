import { createContext } from "svelte";
import { SvelteMap } from "svelte/reactivity";
import { readJson, writeJson } from "../utils/storage";

const STORAGE_KEY = "sections_open_by_view";
/** Views whose sections stay as the user left them across visits and reloads. */
const REMEMBERED_VIEWS = new Set(["filters"]);

/** Names the view collapsible sections are shown in. */
export const [getSectionView, setSectionView] = createContext<string>();

function remembered(key: string): boolean {
  return REMEMBERED_VIEWS.has(key.slice(0, key.indexOf("/")));
}

/**
 * Which collapsible sections the user opened or closed, by view and title.
 *
 * The choice outlives the component, so a section remounted by a refetch or a
 * keyed block, or given a new default, keeps it. Only remembered views keep it
 * across visits; a form calls `forget` as it opens and starts at its defaults.
 */
class SectionState {
  readonly #open = new SvelteMap<string, boolean>(
    Object.entries(readJson<Record<string, boolean>>(STORAGE_KEY, {})).filter(([key]) =>
      remembered(key),
    ),
  );

  /** Whether *title* is open in *view*; *fallback* until the user has chosen. */
  isOpen(view: string, title: string, fallback: boolean): boolean {
    return this.#open.get(`${view}/${title}`) ?? fallback;
  }

  setOpen(view: string, title: string, open: boolean) {
    const key = `${view}/${title}`;
    this.#open.set(key, open);
    if (remembered(key))
      writeJson(
        STORAGE_KEY,
        Object.fromEntries([...this.#open].filter(([entry]) => remembered(entry))),
      );
  }

  /** Return *view*'s sections to their defaults. */
  forget(view: string) {
    for (const key of [...this.#open.keys()])
      if (key.startsWith(`${view}/`)) this.#open.delete(key);
  }

  /** Forget every choice, as on a fresh browser. */
  reset() {
    this.#open.clear();
  }
}

export const sectionState = new SectionState();
