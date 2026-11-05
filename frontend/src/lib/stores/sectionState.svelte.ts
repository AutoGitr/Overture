import { createContext } from "svelte";
import { SvelteMap } from "svelte/reactivity";
import { readJson, writeJson } from "../utils/storage";

const STORAGE_KEY = "sections_open_by_view";
/** Views whose sections stay as the user left them across visits and reloads. */
const REMEMBERED_VIEWS = new Set(["filters", "collection-groups"]);

/** Names the view collapsible sections are shown in. */
export const [getSectionView, setSectionView] = createContext<string>();

function remembered(key: string): boolean {
  return REMEMBERED_VIEWS.has(key.slice(0, key.indexOf("/")));
}

/**
 * Which collapsible sections the user opened or closed, by view and title.
 *
 * The choice outlives the component: a section remounted by navigation, a
 * refetch or a keyed block, or given a new default, keeps it. Only remembered
 * views keep it across reloads; a record's page starts over for each record.
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

  /**
   * Open *view*, such as `collection:12`, with its sections at their defaults
   * unless it is the record already shown; other records of its kind forget theirs.
   */
  enter(view: string) {
    const kind = `${view.slice(0, view.indexOf(":"))}:`;
    for (const key of [...this.#open.keys()])
      if (key.startsWith(kind) && !key.startsWith(`${view}/`)) this.#open.delete(key);
  }

  /** Forget every choice, as on a fresh browser. */
  reset() {
    this.#open.clear();
  }
}

export const sectionState = new SectionState();
