import { readJson, writeJson } from "../utils/storage";

/** The groups and collections a shortcut opens the Sync tab with. */
export interface SyncFocus {
  groups?: string[];
  collectionIds?: number[];
}

/** What the Sync tab runs; a run or schedule saves it for the next visit. */
class SyncSelection {
  /** The chosen libraries; `null` until a choice is made means all of them. */
  libraries = $state<string[] | null>(null);
  allCollections = $state(true);
  groups = $state<string[]>([]);
  collectionIds = $state<number[]>([]);
  #focused = false;

  /** Start a visit from the saved choice, unless a shortcut just chose what to sync. */
  restore(): void {
    if (this.#focused) {
      this.#focused = false;
      return;
    }
    this.libraries = readJson<string[] | null>("syncPopup_selectedLibraries", null);
    this.allCollections = readJson<boolean>("syncPopup_includeCollections", true);
    this.groups = readJson<string[]>("syncPopup_collectionGroups", []);
    this.collectionIds = readJson<unknown[]>("syncPopup_collectionIds", []).filter(
      (id): id is number => typeof id === "number",
    );
  }

  /** Remember the choice, with the libraries it resolved to. */
  save(libraries: string[]): void {
    writeJson("syncPopup_selectedLibraries", libraries);
    writeJson("syncPopup_includeCollections", this.allCollections);
    writeJson("syncPopup_collectionGroups", this.groups);
    writeJson("syncPopup_collectionIds", this.collectionIds);
  }

  /** Choose only these groups and collections, and no library, for the next visit. */
  focus({ groups = [], collectionIds = [] }: SyncFocus): void {
    this.libraries = [];
    this.allCollections = false;
    this.groups = groups;
    this.collectionIds = collectionIds;
    this.#focused = true;
  }
}

export const syncSelection = new SyncSelection();
