import { createContext } from "svelte";
import { SvelteMap } from "svelte/reactivity";
import { readJson, writeJson } from "../utils/storage";

const STORAGE_KEY = "sections_open_by_view";

/**
 * Which collapsible sections of one view are open.
 *
 * The view owns the choices, so a section remounted by a refetch or a keyed
 * block keeps the one made there, and every new view starts as it declares.
 * Only a view given a name to remember them by keeps them across visits and
 * reloads.
 */
export class SectionView {
  readonly #open: SvelteMap<string, boolean>;

  /**
   * @param startsOpen Whether a section, by title, is open until someone
   *   opens or closes it.
   * @param remembered The name the view keeps its choices under.
   */
  constructor(
    private readonly startsOpen: (title: string) => boolean,
    private readonly remembered?: string,
  ) {
    const prefix = `${remembered}/`;
    this.#open = new SvelteMap(
      remembered === undefined
        ? []
        : Object.entries(readJson<Record<string, boolean>>(STORAGE_KEY, {}))
            .filter(([key]) => key.startsWith(prefix))
            .map(([key, open]) => [key.slice(prefix.length), open]),
    );
  }

  isOpen(title: string): boolean {
    return this.#open.get(title) ?? this.startsOpen(title);
  }

  setOpen(title: string, open: boolean) {
    this.#open.set(title, open);
    if (this.remembered === undefined) return;
    const prefix = `${this.remembered}/`;
    writeJson(STORAGE_KEY, {
      ...Object.fromEntries(
        Object.entries(readJson<Record<string, boolean>>(STORAGE_KEY, {})).filter(
          ([key]) => !key.startsWith(prefix),
        ),
      ),
      ...Object.fromEntries([...this.#open].map(([key, value]) => [`${prefix}${key}`, value])),
    });
  }
}

/** The sections of the view a component is shown in. */
export const [getSectionView, setSectionView] = createContext<SectionView>();

/** The sections a collection or group opens with: what it is and what it holds. */
const CONFIGURE_OPEN = new Set(["Setup", "Content"]);

/**
 * A collection's or group's sections, saved or new: each time one is opened,
 * Setup and Content are open and every other section is closed.
 */
export function configureSections(): SectionView {
  return new SectionView((title) => CONFIGURE_OPEN.has(title));
}
