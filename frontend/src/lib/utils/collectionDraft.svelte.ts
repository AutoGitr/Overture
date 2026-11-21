import { createMutation, createQuery } from "@tanstack/svelte-query";
import { SvelteMap } from "svelte/reactivity";
import { UNGROUPED_GROUP, UNMANAGED_GROUP } from "../../generated/settings";
import {
  createCollectionMutation,
  getCollectionDefaultsOptions,
  getCollectionGroupPolicyOptions,
  listCollectionSetsOptions,
  listCollectionsOptions,
  saveCollectionGroupPolicyMutation,
} from "../../generated/rest/@tanstack/svelte-query.gen";
import type {
  CollectionDimensionRead,
  CollectionFiltering,
  CollectionLibraryCriteriaInput,
  CollectionMode,
  CollectionOrder,
  FilterGroupInput,
  LibrarySectionRead,
  MediaType,
  TmdbCollectionResponse,
} from "../../generated/rest/types.gen";
import { storeCollectionDetail } from "../rest/cache";
import { queryClient } from "../rest/queryClient";
import { goToCollection, goToCollectionsList } from "../router/routes";
import { createNotifier } from "../stores/notificationState.svelte";
import { settingsState } from "../stores/settingsState.svelte";
import { emptyGroup, franchiseCriteria } from "./collectionCriteria";
import {
  CollectionRuleForm,
  defaultGenerator,
  defaultRule,
  optionsBody,
  ruleBody,
  setLibrary,
  withDimension,
  type DraftKind,
  type SetGenerator,
  type SetPolicy,
} from "./collectionFormShared.svelte";
import { CriteriaPreview } from "./criteriaPreview.svelte";
import { errorMessage } from "./errors";
import { CollectionOptions as Capabilities } from "./libraries.svelte";
import { openSync } from "./syncShortcut";

/** Something a new set's form found that the person should know before saving. */
type SetNotice = {
  tone: "error" | "warning" | "info";
  title: string;
  message: string;
  group?: string;
};

function sameName(a: string, b: string) {
  return a.trim().toLocaleLowerCase() === b.trim().toLocaleLowerCase();
}

/** An unsaved collection or collection set, created when its form is submitted. */
export class CollectionDraft extends CollectionRuleForm {
  readonly defaults;
  readonly options: Capabilities;
  /** Criteria of a library just left, so swapping one for another keeps them. */
  readonly lastCriteria = new SvelteMap<MediaType, FilterGroupInput>();
  readonly creating = true;
  readonly manualMembersAllowed = false;
  readonly generated = false;
  kind = $state<DraftKind>("collection");
  title = $derived.by(() => this.seed()?.title ?? "");
  sortTitleFormat = $state("");
  collectionGroup = $state("");
  tmdbCollectionId = $derived.by(() => this.seed()?.tmdb_id);
  collectionMode = $state<CollectionMode | null>(null);
  visibleHome = $state<boolean | null>(null);
  summaryFormat = $state("");
  activeStartMmdd = $state("");
  activeEndMmdd = $state("");
  deleteWhenInactive = $state<boolean | null>(null);
  collectionFiltering = $state<CollectionFiltering | null>(null);
  visibleShared = $state<boolean | null>(null);
  visibleLibrary = $state<boolean | null>(null);
  orderType = $state<CollectionOrder | null>(null);
  /** The rule starts over as the seed and the libraries arrive; edits follow them. */
  rule = $derived.by(() => {
    const seed = this.seed();
    const rule = $state({
      ...defaultRule(),
      libraries: this.startingLibraries(seed),
    });
    return rule;
  });
  /** The group policy and generator a new set saves. */
  setPolicy = $state<SetPolicy>({});
  generator = $state<SetGenerator>(defaultGenerator());
  readonly preview: CriteriaPreview;
  readonly request = createMutation(() => createCollectionMutation());
  private readonly groupRequest = createMutation(() => saveCollectionGroupPolicyMutation());
  private readonly feedback = createNotifier();
  private readonly sets = createQuery(() => listCollectionSetsOptions());
  private readonly collections = createQuery(() => ({
    ...listCollectionsOptions(),
    enabled: this.kind === "set",
  }));

  constructor(
    private readonly libraries: () => LibrarySectionRead[],
    private readonly seed: () => TmdbCollectionResponse | null,
  ) {
    super();
    this.defaults = createQuery(() =>
      getCollectionDefaultsOptions({
        query: { name: this.collectionGroup || undefined },
      }),
    );
    // Last: their queries read the form as soon as they are created.
    this.options = new Capabilities(() =>
      this.libraryIds.map((id) => ({ id, media_type: this.typeOf(id) })),
    );
    this.preview = new CriteriaPreview(() => this);
  }

  typeOf(libraryId: string): MediaType {
    return this.libraries().find((library) => library.id === libraryId)?.media_type ?? "movie";
  }
  /** A franchise holds movies, so a seeded form starts with its only movie library. */
  private startingLibraries(seed: TmdbCollectionResponse | null): CollectionLibraryCriteriaInput[] {
    const candidates = seed
      ? this.libraries().filter((library) => library.media_type === "movie")
      : this.libraries();
    return candidates.length === 1
      ? [{ library_id: candidates[0]?.id ?? "", criteria: this.fallbackCriteria(seed) }]
      : [];
  }
  private fallbackCriteria(seed: TmdbCollectionResponse | null) {
    return seed ? franchiseCriteria(seed.tmdb_id) : emptyGroup();
  }
  setLibrary(libraryId: string, chosen: boolean) {
    const seed = this.typeOf(libraryId) === "movie" ? this.seed() : null;
    setLibrary(this, libraryId, chosen, this.fallbackCriteria(seed));
  }
  /** What a set can test: only what every one of its libraries holds. */
  get setCapabilities() {
    return this.options.shared(this.mediaTypes);
  }
  /** The group a set saves into: the one named, or else the dimension's name. */
  get setGroup() {
    return (
      this.collectionGroup.trim() ||
      this.dimensions.find((entry) => entry.dimension === this.generator.dimension)?.label ||
      ""
    );
  }
  get busy() {
    return this.request.isPending || this.groupRequest.isPending;
  }
  private dimensionLabel(dimension: string) {
    return (
      this.dimensions.find((entry) => entry.dimension === dimension)?.label.toLowerCase() ??
      dimension
    );
  }

  private libraryNames(ids: string[]) {
    return ids
      .map((id) => {
        const library = this.libraries().find((each) => each.id === id);
        return library ? settingsState.libraryLabel(library) : id;
      })
      .join(", ");
  }

  get groupHint(): string | null {
    const set = (this.sets.data ?? []).find((entry) => sameName(entry.group, this.collectionGroup));
    return set
      ? `"${set.group}" is a set that splits by ${this.dimensionLabel(set.dimension)}; this collection sits beside the ones it makes and inherits the group's defaults.`
      : null;
  }

  get setNotices(): SetNotice[] {
    const name = this.setGroup;
    if (this.kind !== "set" || !name) return [];
    if ([UNGROUPED_GROUP, UNMANAGED_GROUP].some((reserved) => sameName(reserved, name)))
      return [
        {
          tone: "error",
          title: `"${name}" is reserved`,
          message: "Overture keeps it for collections outside any group; name another group.",
        },
      ];
    const sets = this.sets.data ?? [];
    const existing = sets.find((set) => sameName(set.group, name));
    if (existing)
      return [
        {
          tone: "error",
          title: `"${existing.group}" already is a set`,
          message: `It splits ${this.libraryNames(existing.library_ids)} by ${this.dimensionLabel(existing.dimension)}. Edit that set in the group's settings, or name another group.`,
          group: existing.group,
        },
      ];
    const notices: SetNotice[] = [];
    const held = (this.collections.data ?? []).filter(
      (row) => row.managed && row.collection_group !== null && sameName(row.collection_group, name),
    );
    if (held.length)
      notices.push({
        tone: "info",
        title: `"${held[0]?.collection_group}" already holds ${held.length === 1 ? "a collection" : `${held.length} collections`}`,
        message:
          "They stay in the group beside the set's collections. A value whose title one of them has is skipped until one is renamed; the preview names those values.",
      });
    for (const set of sets) {
      const shared = set.library_ids.filter((id) => this.libraryIds.includes(id));
      if (set.dimension !== this.generator.dimension || !shared.length) continue;
      notices.push({
        tone: "warning",
        title: `"${set.group}" already splits by ${this.dimensionLabel(set.dimension)}`,
        message: `It covers ${this.libraryNames(shared)}, so this set makes a second collection per value there. Narrow one of them with criteria, or edit that set instead.`,
        group: set.group,
      });
    }
    return notices;
  }

  /** Why the form cannot be saved yet, or null when it can. */
  get blocker(): string | null {
    if (!this.libraryIds.length) return "Choose a library";
    if (this.kind === "set") {
      if (!this.setGroup) return "Name the set's group";
      return this.setNotices.find((notice) => notice.tone === "error")?.title ?? null;
    }
    if (!this.title.trim()) return "Enter a title";
    return null;
  }

  selectKind(kind: DraftKind) {
    this.kind = kind;
    const dimension = this.dimensions.find((entry) => entry.dimension === this.generator.dimension);
    if (kind === "set" && dimension && !this.collectionGroup) this.chooseDimension(dimension);
  }

  get dimensions() {
    return this.setCapabilities?.dimensions ?? [];
  }

  /**
   * Split the set by a dimension: it names the group, unless one was typed,
   * and starts the set and its collections with the dimension's defaults.
   */
  chooseDimension(dimension: CollectionDimensionRead) {
    const previous = this.dimensions.find((entry) => entry.dimension === this.generator.dimension);
    if (!this.collectionGroup.trim() || this.collectionGroup === previous?.label)
      this.collectionGroup = dimension.label;
    this.generator = withDimension(this.generator, dimension, previous);
    this.setPolicy = { ...this.setPolicy, order_type: dimension.order_type };
  }

  /** Save in Overture; with `sync`, then open Sync with only what was saved chosen. */
  async save(sync = false) {
    if (this.busy) return false;
    return this.kind === "set" ? this.saveSet(sync) : this.saveCollection(sync);
  }

  private async saveCollection(sync: boolean) {
    try {
      const collection = await this.request.mutateAsync({
        body: { ...optionsBody(this), rule: ruleBody(this) },
      });
      storeCollectionDetail(collection);
      goToCollection(collection);
      if (sync) await openSync({ collectionIds: [collection.id] });
      return true;
    } catch (error) {
      this.feedback.error(errorMessage(error, "Could not save the collection"));
      return false;
    }
  }

  /** Save the set into its group, keeping the group's other defaults. */
  private async saveSet(sync: boolean) {
    const name = this.setGroup;
    const query = { name };
    try {
      const existing = await queryClient.fetchQuery(getCollectionGroupPolicyOptions({ query }));
      // A choice left at Default keeps what an existing group already has.
      const chosen = Object.fromEntries(
        Object.entries($state.snapshot(this.setPolicy)).filter(([, value]) => value !== null),
      );
      const saved = await this.groupRequest.mutateAsync({
        query: { ...query, new_set: true },
        body: {
          ...existing,
          ...chosen,
          generator: { ...$state.snapshot(this.generator), library_ids: this.libraryIds },
        },
      });
      queryClient.setQueryData(getCollectionGroupPolicyOptions({ query }).queryKey, saved);
      goToCollectionsList(name);
      if (sync) await openSync({ groups: [name] });
      else this.feedback.success(`Saved "${name}". Sync the group to create its collections.`);
      return true;
    } catch (error) {
      this.feedback.error(errorMessage(error, "Could not save the set"));
      return false;
    }
  }
}
