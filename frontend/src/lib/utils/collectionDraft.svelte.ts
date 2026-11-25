import { createMutation, createQuery } from "@tanstack/svelte-query";
import { SvelteMap } from "svelte/reactivity";
import { UNMANAGED_GROUP } from "../../generated/settings";
import {
  createCollectionMutation,
  getCollectionGroupPolicyOptions,
  listCollectionGroupsOptions,
  listCollectionPresetsOptions,
  listCollectionsOptions,
  readCollectionPresetFileMutation,
  saveCollectionArtMutation,
  saveCollectionGroupPolicyMutation,
} from "../../generated/rest/@tanstack/svelte-query.gen";
import type {
  CollectionDimensionRead,
  CollectionFiltering,
  CollectionLibraryCriteriaOutput,
  CollectionMode,
  CollectionOrder,
  CollectionPresetFileInput,
  FilterGroupOutput,
  LibrarySectionRead,
  MediaType,
  PortableCollectionOutput,
  PortableGroupOutput,
  PortableSetOutput,
  PresetArtOutput,
  PresetListing,
  TmdbCollectionResponse,
} from "../../generated/rest/types.gen";
import { storeCollectionDetail } from "../rest/cache";
import { queryClient } from "../rest/queryClient";
import { goToCollection, goToGroup } from "../router/routes";
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
  type DraftKind,
} from "./collectionFormShared.svelte";
import { CollectionGroupForm } from "./collectionGroupForm.svelte";
import { CriteriaPreview } from "./criteriaPreview.svelte";
import { errorMessage } from "./errors";
import type { CollectionOptions as Capabilities } from "./libraries.svelte";
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

/** A group's defaults as a file holds them, without what names it or makes it a set. */
function groupPolicy({ name: _name, generator: _generator, ...policy }: PortableGroupOutput) {
  return policy;
}

/** Literal text as a template keeps it, as the server quotes it. */
function literal(text: string | null) {
  return text?.replaceAll("{", "{{").replaceAll("}", "}}") ?? null;
}

/** One collection or set of a preset or file, which fills the form. */
export type PresetItem = {
  listing: PresetListing;
  kind: "collection" | "set";
  name: string;
};

/** An unsaved collection or collection set, created when its form is submitted. */
export class CollectionDraft extends CollectionRuleForm {
  readonly defaults;
  readonly options: Capabilities;
  /** Criteria of a library just left, so swapping one for another keeps them. */
  readonly lastCriteria = new SvelteMap<MediaType, FilterGroupOutput>();
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
  /** The group a new set saves: its defaults and what it creates. */
  readonly set: CollectionGroupForm;
  readonly preview: CriteriaPreview;
  readonly request = createMutation(() => createCollectionMutation());
  private readonly groupRequest = createMutation(() => saveCollectionGroupPolicyMutation());
  private readonly artRequest = createMutation(() => saveCollectionArtMutation());
  /** OvertureDB's presets, whose collections and sets fill the form. */
  readonly presets = createQuery(() => listCollectionPresetsOptions());
  readonly fileRequest = createMutation(() => readCollectionPresetFileMutation());
  /** A collections file read from disk, listed as a preset is. */
  file = $state.raw<PresetListing | null>(null);
  /** The preset item filling the form. */
  preset = $state.raw<PresetItem | null>(null);
  /**
   * The group a filled-in collection joins, as its preset gives it; saving
   * gives the group these defaults wherever it leaves one at Default.
   */
  presetGroup = $state.raw<PortableGroupOutput | null>(null);
  /** The art a filled-in collection starts with. */
  private presetArt: PresetArtOutput | null = null;
  private readonly feedback = createNotifier();
  private readonly groups = createQuery(() => listCollectionGroupsOptions());
  private readonly collections = createQuery(() => ({
    ...listCollectionsOptions(),
    enabled: this.kind === "set",
  }));

  constructor(
    private readonly libraries: () => LibrarySectionRead[],
    private readonly seed: () => TmdbCollectionResponse | null,
  ) {
    super();
    ({ defaults: this.defaults, options: this.options } = this.formQueries());
    this.preview = new CriteriaPreview(() => this);
    this.set = new CollectionGroupForm(libraries, () => []);
  }

  typeOf(libraryId: string): MediaType {
    return this.libraries().find((library) => library.id === libraryId)?.media_type ?? "movie";
  }
  /** A franchise holds movies, so a seeded form starts with its only movie library. */
  private startingLibraries(
    seed: TmdbCollectionResponse | null,
  ): CollectionLibraryCriteriaOutput[] {
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
  /** Choose a library in Setup, which a new set spans as well. */
  setLibrary(libraryId: string, chosen: boolean) {
    const seed = this.typeOf(libraryId) === "movie" ? this.seed() : null;
    setLibrary(this, libraryId, chosen, this.fallbackCriteria(seed));
    this.set.setLibrary(libraryId, chosen);
  }
  /** The group a set saves into: the one named, or else the dimension's name. */
  get setGroup() {
    const dimension = this.set.generator?.dimension;
    return (
      this.collectionGroup.trim() ||
      this.set.dimensions.find((entry) => entry.dimension === dimension)?.label ||
      ""
    );
  }
  get busy() {
    return this.request.isPending || this.set.busy || this.groupRequest.isPending;
  }
  private dimensionLabel(dimension: string) {
    return (
      this.set.dimensions.find((entry) => entry.dimension === dimension)?.label.toLowerCase() ??
      dimension
    );
  }
  /** The groups that are sets, with what each splits by. */
  private get sets() {
    return (this.groups.data ?? []).flatMap((group) =>
      group.set ? [{ group: group.name, ...group.set }] : [],
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
    const set = this.sets.find((entry) => sameName(entry.group, this.collectionGroup));
    return set
      ? `"${set.group}" is a set that splits by ${this.dimensionLabel(set.dimension)}; this collection sits beside the ones it makes and inherits the group's defaults.`
      : null;
  }

  get setNotices(): SetNotice[] {
    const name = this.setGroup;
    if (this.kind !== "set" || !name) return [];
    if (sameName(UNMANAGED_GROUP, name))
      return [
        {
          tone: "error",
          title: `"${name}" is reserved`,
          message: "Overture keeps it for the collections it does not manage; name another group.",
        },
      ];
    const sets = this.sets;
    const existing = sets.find((set) => sameName(set.group, name));
    if (existing)
      return [
        {
          tone: "error",
          title: `"${existing.group}" already is a set`,
          message: `It splits ${this.libraryNames(existing.library_ids)} by ${this.dimensionLabel(existing.dimension)}. Edit that set on its group's page, or name another group.`,
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
      if (set.dimension !== this.set.generator?.dimension || !shared.length) continue;
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
    if (!this.collectionGroup.trim()) return "Choose a group";
    return null;
  }

  selectKind(kind: DraftKind) {
    this.kind = kind;
    if (kind !== "set") return;
    this.set.generator ??= defaultGenerator(this.libraryIds);
    const dimension = this.set.dimensions.find(
      (entry) => entry.dimension === this.set.generator?.dimension,
    );
    if (dimension && !this.collectionGroup) this.chooseDimension(dimension);
  }

  /**
   * Split the set by a dimension: it names the group, unless one was typed,
   * and starts the set and its collections with the dimension's defaults.
   */
  chooseDimension(dimension: CollectionDimensionRead) {
    const previous = this.set.dimensions.find(
      (entry) => entry.dimension === this.set.generator?.dimension,
    );
    if (!this.collectionGroup.trim() || this.collectionGroup === previous?.label)
      this.collectionGroup = dimension.label;
    this.set.chooseDimension(dimension);
  }

  /** Read a collections file exported from Overture, offering its items beside the presets. */
  async loadFile(file: File) {
    this.feedback.clear();
    let body: CollectionPresetFileInput;
    try {
      body = JSON.parse(await file.text()) as CollectionPresetFileInput;
    } catch {
      this.feedback.error(`${file.name} is not a collections file exported from Overture`);
      return;
    }
    try {
      this.file = await this.fileRequest.mutateAsync({ body });
    } catch (error) {
      this.feedback.error(errorMessage(error, `Could not read ${file.name}`));
    }
  }

  /**
   * Fill the form with a preset's collection or set, in every library of the
   * media types it holds; the libraries and everything else stay editable.
   */
  applyPreset(item: PresetItem) {
    const file = item.listing.file;
    if (!file) return;
    this.preset = item;
    this.presetArt = null;
    this.presetGroup = null;
    this.lastCriteria.clear();
    if (item.kind === "set") {
      const group = file.groups.find((each) => each.name === item.name);
      if (group?.generator) this.fillSet(group, group.generator);
      return;
    }
    const collection = file.collections.find((each) => each.title === item.name);
    if (!collection) return;
    this.fillCollection(collection);
    this.presetGroup =
      file.groups.find(
        (group) => !group.generator && sameName(group.name, collection.collection_group ?? ""),
      ) ?? null;
    this.presetArt = collection.art;
  }

  private fillSet(group: PortableGroupOutput, set: PortableSetOutput) {
    const { media_types: mediaTypes, ...generator } = set;
    const rule = $state({
      ...defaultRule(),
      libraries: this.libraries()
        .filter((library) => mediaTypes.includes(library.media_type))
        .map((library) => ({ library_id: library.id, criteria: emptyGroup() })),
    });
    this.kind = "set";
    this.rule = rule;
    this.collectionGroup = group.name;
    this.set.reset({
      ...groupPolicy(group),
      generator: { ...defaultGenerator(this.libraryIds), ...structuredClone(generator) },
    });
  }

  private fillCollection(collection: PortableCollectionOutput) {
    const { policy } = collection;
    for (const mediaType of ["movie", "show"] as const) {
      const criteria = collection.criteria[mediaType];
      // A library of the kind chosen later starts with the preset's criteria.
      if (criteria) this.lastCriteria.set(mediaType, criteria);
    }
    const rule = $state({
      ...defaultRule(),
      ...policy,
      smart: collection.smart,
      limit: collection.limit,
      libraries: this.libraries().flatMap((library) => {
        const criteria = collection.criteria[library.media_type];
        return criteria ? [{ library_id: library.id, criteria: structuredClone(criteria) }] : [];
      }),
    });
    this.kind = "collection";
    this.rule = rule;
    this.title = collection.title;
    this.collectionGroup = collection.collection_group ?? "";
    this.tmdbCollectionId = collection.tmdb_collection_id ?? undefined;
    this.sortTitleFormat =
      collection.sort_title_format ??
      policy.sort_title_format ??
      literal(collection.sort_title) ??
      "";
    this.summaryFormat =
      collection.summary_format ?? policy.summary_format ?? literal(collection.summary) ?? "";
    this.activeStartMmdd = collection.active_start_mmdd ?? policy.active_start_mmdd ?? "";
    this.activeEndMmdd = collection.active_end_mmdd ?? policy.active_end_mmdd ?? "";
    this.deleteWhenInactive = collection.delete_when_inactive ?? policy.delete_when_inactive;
    this.fillDisplay(collection);
  }

  /** How the server shows a filled-in collection: its own choice, else its policy's. */
  private fillDisplay({ policy, ...collection }: PortableCollectionOutput) {
    this.collectionFiltering = collection.collection_filtering ?? policy.collection_filtering;
    this.collectionMode = collection.collection_mode ?? policy.collection_mode;
    this.orderType = collection.order_type ?? policy.order_type;
    // A file cannot tell a collection left hidden from one hidden on purpose,
    // so only a shown one is its own choice.
    this.visibleHome = collection.visible_home || policy.visible_home;
    this.visibleShared = collection.visible_shared || policy.visible_shared;
    this.visibleLibrary = collection.visible_library || policy.visible_library;
  }

  /** Give the collection's group its preset's defaults where the group leaves them at Default. */
  private async fillGroup() {
    if (!this.presetGroup || !sameName(this.presetGroup.name, this.collectionGroup)) return;
    const path = { name: this.collectionGroup.trim() };
    const existing = await queryClient.fetchQuery(getCollectionGroupPolicyOptions({ path }));
    const missing = Object.fromEntries(
      Object.entries(groupPolicy(this.presetGroup)).filter(
        ([key, value]) => value !== null && existing[key as keyof typeof existing] == null,
      ),
    );
    if (!Object.keys(missing).length) return;
    const saved = await this.groupRequest.mutateAsync({ path, body: { ...existing, ...missing } });
    queryClient.setQueryData(getCollectionGroupPolicyOptions({ path }).queryKey, saved);
  }

  /** Choose the art a filled-in collection starts with; failing leaves the collection saved. */
  private async applyArt(collectionId: number) {
    const art = this.presetArt;
    try {
      if (art?.poster)
        await this.artRequest.mutateAsync({
          path: { collection_id: collectionId, art_type: "poster" },
          body: { url: art.poster.url, poster_style: art.poster.style },
        });
      if (art?.background)
        await this.artRequest.mutateAsync({
          path: { collection_id: collectionId, art_type: "background" },
          body: { url: art.background.url },
        });
    } catch (error) {
      this.feedback.error(errorMessage(error, "Saved the collection, but not its art"));
    }
  }

  /** Save in Overture; with `sync`, then open Sync with only what was saved chosen. */
  async save(sync = false) {
    if (this.busy) return false;
    return this.kind === "set" ? this.saveSet(sync) : this.saveCollection(sync);
  }

  private async saveCollection(sync: boolean) {
    try {
      await this.fillGroup();
      const collection = await this.request.mutateAsync({
        body: { ...optionsBody(this), rule: ruleBody(this) },
      });
      await this.applyArt(collection.id);
      storeCollectionDetail(collection);
      goToCollection(collection);
      if (sync) await openSync({ collectionIds: [collection.id] });
      return true;
    } catch (error) {
      this.feedback.error(errorMessage(error, "Could not save the collection"));
      return false;
    }
  }

  /** Save the set into its group, then open the group. */
  private async saveSet(sync: boolean) {
    const name = this.setGroup;
    if (!(await this.set.save(name, true))) return false;
    goToGroup(name);
    if (sync) await openSync({ groups: [name] });
    else this.feedback.success(`Saved "${name}". Sync the group to create its collections.`);
    return true;
  }
}
