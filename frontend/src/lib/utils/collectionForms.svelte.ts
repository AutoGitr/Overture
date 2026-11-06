import { createMutation, createQuery, keepPreviousData } from "@tanstack/svelte-query";
import { UNGROUPED_GROUP } from "../../generated/settings";
import { SvelteMap, SvelteSet } from "svelte/reactivity";
import {
  createCollectionMutation,
  deleteCollectionMutation,
  orphanCollectionMutation,
  getCollectionDefaultsOptions,
  getCollectionGroupPolicyOptions,
  previewCollectionMutation,
  recommendCollectionKindOptions,
  saveCollectionGroupPolicyMutation,
  saveCollectionRuleMutation,
  setCollectionMembersMutation,
  syncCollectionGroupMutation,
  syncCollectionMutation,
  updateCollectionMutation,
} from "../../generated/rest/@tanstack/svelte-query.gen";
import type {
  CollectionDetail,
  CollectionDimensionRead,
  CollectionLibraryCriteriaInput,
  DeleteCollectionData,
  CollectionFiltering,
  CollectionGeneratorInput,
  CollectionMode,
  CollectionOptions,
  CollectionGroupPolicyInput,
  CollectionOrder,
  CollectionRuleWriteInput,
  FilterGroupInput,
  LibrarySectionRead,
  MediaItemRead,
  MediaType,
  TmdbCollectionResponse,
} from "../../generated/rest/types.gen";
import { patchCollectionRule, storeCollectionDetail } from "../rest/cache";
import type { PolicyData } from "../components/CollectionPolicyFields.svelte";
import type { ScheduleData } from "../components/CollectionScheduleFields.svelte";
import { queryClient } from "../rest/queryClient";
import { goToCollection, goToCollectionsList } from "../router/routes";
import { chooseAction, confirmAction, createNotifier } from "../stores/notificationState.svelte";
import { settingsState } from "../stores/settingsState.svelte";
import {
  availableFields,
  availableOrders,
  emptyGroup,
  franchiseCriteria,
} from "./collectionCriteria";
import { errorMessage } from "./errors";
import { CollectionOptions as Capabilities } from "./libraries.svelte";

/** Make the criteria Plex's live filter or Overture's, dropping an order the new kind cannot keep. */
export function switchKind(form: CollectionEditor | CollectionDraft, smart: boolean) {
  form.rule.smart = smart;
  if (form.orderType !== null && !form.orders.includes(form.orderType)) form.orderType = null;
}

/** What a new collection form creates. */
export type DraftKind = "collection" | "set";

export function defaultRule(): CollectionRuleWriteInput {
  return {
    libraries: [],
    smart: false,
    limit: null,
    sync_mode: null,
    minimum_items: null,
    delete_below_minimum: null,
    auto_match_art: null,
    auto_match_theme: null,
    collection_mode: null,
    collection_filtering: null,
    visible_home: null,
    visible_shared: null,
    visible_library: null,
    order_type: null,
    sort_title_format: null,
    summary_format: null,
    active_start_mmdd: null,
    active_end_mmdd: null,
    delete_when_inactive: null,
    request_missing: null,
    member_label: null,
    arr_tag: null,
    home_order: null,
  };
}

/** A set's generator, whose criteria the form always edits in place. */
export type SetGenerator = CollectionGeneratorInput & { criteria: FilterGroupInput };
/** The defaults a set's group gives its collections. */
export type SetPolicy = Omit<CollectionGroupPolicyInput, "generator">;

/**
 * A generator split by *dimension*, starting with what the dimension starts sets with.
 * Only Plex can count a smart-only dimension, so it makes the set smart; leaving one
 * for a dimension Overture counts returns the set to Overture's evaluation.
 */
export function withDimension(
  generator: SetGenerator,
  dimension: CollectionDimensionRead,
  previous: CollectionDimensionRead | undefined,
): SetGenerator {
  return {
    ...generator,
    dimension: dimension.dimension,
    title_format: dimension.title_format,
    strip_prefix: dimension.strip_prefix,
    strip_suffix: dimension.strip_suffix,
    smart: dimension.smart_only || (!!generator.smart && !previous?.smart_only),
    custom_values:
      dimension.dimension === "custom"
        ? generator.custom_values?.length
          ? generator.custom_values
          : [{ name: "", criteria: emptyGroup() }]
        : [],
  };
}

export function defaultGenerator(libraryIds: string[] = []): SetGenerator {
  return {
    dimension: "decade",
    library_ids: libraryIds,
    include: [],
    exclude: [],
    top: null,
    title_format: "{value}s",
    strip_prefix: "",
    strip_suffix: "",
    criteria: emptyGroup(),
    smart: false,
    custom_values: [],
    aliases: [],
  };
}

type CollectionForm = CollectionEditor | CollectionDraft;

/** Radarr, Sonarr or both, as far as the form's libraries can use them. */
function arrName(form: CollectionForm): string | null {
  const names = { movie: "Radarr", show: "Sonarr" } as const;
  const usable = form.mediaTypes.filter((mediaType) => form.options.for(mediaType).data?.arr);
  return usable.map((mediaType) => names[mediaType]).join(" and ") || null;
}

function heldTypes(libraryIds: string[], typeOf: (id: string) => MediaType): MediaType[] {
  const held = new Set(libraryIds.map(typeOf));
  return (["movie", "show"] as const).filter((mediaType) => held.has(mediaType));
}

/** The rule a form saves; display choices are the rule's overrides. */
function ruleBody(form: CollectionForm): CollectionRuleWriteInput {
  return {
    ...$state.snapshot(form.rule),
    sort_title_format: null,
    summary_format: null,
    collection_mode: form.collectionMode,
    collection_filtering: form.collectionFiltering,
    order_type: form.orderType,
    visible_home: form.visibleHome,
    visible_shared: form.visibleShared,
    visible_library: form.visibleLibrary,
  };
}

function optionsBody(form: CollectionForm): CollectionOptions {
  return {
    title: form.title.trim(),
    summary: null,
    sort_title: null,
    sort_title_format: form.sortTitleFormat || null,
    summary_format: form.summaryFormat || null,
    active_start_mmdd: form.activeStartMmdd || null,
    active_end_mmdd: form.activeEndMmdd || null,
    delete_when_inactive: form.deleteWhenInactive,
    collection_filtering: form.collectionFiltering,
    collection_group: form.collectionGroup || UNGROUPED_GROUP,
    tmdb_collection_id: form.tmdbCollectionId ?? null,
    collection_mode: form.collectionMode,
    ...(form.orderType === null ? {} : { order_type: form.orderType }),
    ...(form.visibleHome === null ? {} : { visible_home: form.visibleHome }),
    ...(form.visibleShared === null ? {} : { visible_shared: form.visibleShared }),
    ...(form.visibleLibrary === null ? {} : { visible_library: form.visibleLibrary }),
  };
}

/** The criteria a library starts with: another of its kind's, the last one's, or none. */
function startingCriteria(
  form: CollectionForm,
  mediaType: MediaType,
  fallback: FilterGroupInput,
): FilterGroupInput {
  const alike = form.rule.libraries.find((entry) => form.typeOf(entry.library_id) === mediaType);
  return alike
    ? structuredClone($state.snapshot(alike.criteria))
    : (form.lastCriteria.get(mediaType) ?? fallback);
}

/** Add a library to the form's rule, or take it out. */
function setLibrary(
  form: CollectionForm,
  libraryId: string,
  chosen: boolean,
  fallback: FilterGroupInput,
) {
  const leaving = form.rule.libraries.find((entry) => entry.library_id === libraryId);
  if (leaving)
    form.lastCriteria.set(
      form.typeOf(libraryId),
      $state.snapshot(leaving.criteria) as FilterGroupInput,
    );
  form.rule.libraries = chosen
    ? [
        ...form.rule.libraries,
        {
          library_id: libraryId,
          criteria: startingCriteria(form, form.typeOf(libraryId), fallback),
        },
      ]
    : form.rule.libraries.filter((entry) => entry.library_id !== libraryId);
  if (form.orderType !== null && !form.orders.includes(form.orderType)) form.orderType = null;
}

/** Form drafts and actions for one mounted collection. */
export class CollectionEditor {
  readonly defaults;
  readonly options = new Capabilities();
  /** Criteria of a library just left, so swapping one for another keeps them. */
  readonly lastCriteria = new SvelteMap<MediaType, FilterGroupInput>();
  readonly creating = false;
  // Drafts reset when saved fields change, not when unrelated collection data changes.
  private savedTitle = $derived.by(() => this.current().title);
  title = $derived(this.savedTitle);
  private savedSortExpression = $derived.by(
    () => this.current().sort_title_format ?? this.current().rule?.sort_title_format ?? "",
  );
  sortTitleFormat = $derived(this.savedSortExpression);
  private savedGroup = $derived.by(() => this.current().collection_group);
  collectionGroup = $derived(this.savedGroup ?? UNGROUPED_GROUP);
  private savedCollectionMode = $derived.by(() => this.current().rule?.collection_mode ?? null);
  collectionMode = $derived(this.savedCollectionMode);
  private savedVisibleHome = $derived.by(() => this.current().rule?.visible_home ?? null);
  visibleHome = $derived<boolean | null>(this.savedVisibleHome);
  private savedSummaryExpression = $derived.by(
    () => this.current().summary_format ?? this.current().rule?.summary_format ?? "",
  );
  summaryFormat = $derived(this.savedSummaryExpression);
  private savedActiveStart = $derived.by(() => this.current().active_start_mmdd);
  activeStartMmdd = $derived(this.savedActiveStart ?? "");
  private savedActiveEnd = $derived.by(() => this.current().active_end_mmdd);
  activeEndMmdd = $derived(this.savedActiveEnd ?? "");
  private savedDeleteWhenInactive = $derived.by(() => this.current().delete_when_inactive);
  deleteWhenInactive = $derived(this.savedDeleteWhenInactive);
  private savedCollectionFiltering = $derived.by(
    () => this.current().rule?.collection_filtering ?? null,
  );
  collectionFiltering = $derived(this.savedCollectionFiltering);
  private savedVisibleShared = $derived.by(() => this.current().rule?.visible_shared ?? null);
  visibleShared = $derived<boolean | null>(this.savedVisibleShared);
  private savedVisibleLibrary = $derived.by(() => this.current().rule?.visible_library ?? null);
  visibleLibrary = $derived<boolean | null>(this.savedVisibleLibrary);
  private savedTmdbId = $derived.by(() => this.current().tmdb_collection_id);
  tmdbCollectionId = $derived(this.savedTmdbId ?? undefined);
  private savedOrder = $derived.by(() => this.current().rule?.order_type ?? null);
  orderType = $derived<CollectionOrder | null>(this.savedOrder);
  rule = $state<CollectionRuleWriteInput>(defaultRule());

  memberSearch = $state("");
  draggingMemberId = $state<number | null>(null);
  readonly preview: CriteriaPreview;

  private readonly updateRequest = createMutation(() => updateCollectionMutation());
  private readonly membersRequest = createMutation(() => setCollectionMembersMutation());
  private readonly ruleRequest = createMutation(() => saveCollectionRuleMutation());
  private readonly syncRequest = createMutation(() => syncCollectionMutation());
  private readonly deleteRequest = createMutation(() => deleteCollectionMutation());
  private readonly orphanRequest = createMutation(() => orphanCollectionMutation());
  private readonly feedback = createNotifier();

  /** Edits a collection Overture manages; an unmanaged one is only adopted. */
  constructor(
    private readonly current: () => CollectionDetail,
    private readonly libraries: () => LibrarySectionRead[],
  ) {
    this.defaults = createQuery(() =>
      getCollectionDefaultsOptions({
        query: { name: this.collectionGroup || undefined },
      }),
    );
    const saved = this.current().rule;
    if (saved) {
      const {
        last_error: _error,
        last_synced_at: _synced,
        source_summary: _summary,
        ...rest
      } = saved;
      this.rule = structuredClone(rest);
    }
    // Last: its query reads the form as soon as it is created.
    this.preview = new CriteriaPreview(() => this);
  }

  get collection() {
    return this.current();
  }
  get serverType() {
    return this.collection.server_type;
  }
  get libraryIds() {
    return this.rule.libraries.map((entry) => entry.library_id);
  }
  /** What the chosen libraries hold, movies first. */
  get mediaTypes(): MediaType[] {
    return heldTypes(this.libraryIds, (id) => this.typeOf(id));
  }
  get capabilities() {
    return this.options.for(this.mediaTypes[0] ?? "movie");
  }
  /** What takes requests and tags for the chosen libraries. */
  get arr() {
    return arrName(this);
  }
  typeOf(libraryId: string): MediaType {
    return (
      this.libraries().find((library) => library.id === libraryId)?.media_type ??
      this.collection.media_types[0] ??
      "movie"
    );
  }
  setLibrary(libraryId: string, chosen: boolean) {
    setLibrary(this, libraryId, chosen, emptyGroup());
  }
  /** Its collection set decides the criteria and title of a generated collection. */
  get generated() {
    return this.collection.generated_value !== null;
  }
  get smart() {
    return !!this.rule.smart;
  }
  fieldsFor(mediaType: MediaType) {
    return availableFields(this.options.for(mediaType).data, this.smart);
  }
  get orders() {
    return availableOrders(this.options.shared(this.mediaTypes), this.smart);
  }
  /** Append keeps members a sync no longer matches, so members can be added by hand too. */
  get manualMembersAllowed() {
    return (
      this.collection.kind !== "smart" &&
      (this.collection.rule?.sync_mode ?? this.collection.effective_sync_mode) === "append"
    );
  }

  availableMembers(libraryItems: MediaItemRead[]) {
    const query = this.memberSearch.trim().toLowerCase();
    if (!query) return [];
    const memberIds = new SvelteSet(this.collection.members.map((member) => member.id));
    return libraryItems.filter(
      (item) =>
        !!item.library_id &&
        this.collection.library_ids.includes(item.library_id) &&
        item.server_item_id &&
        !item.server_removed_at &&
        !memberIds.has(item.id) &&
        item.title.toLowerCase().includes(query),
    );
  }

  /** Why the form cannot be saved yet, or null when it can. */
  get blocker(): string | null {
    if (!this.title.trim()) return "Enter a title";
    return null;
  }

  get busy() {
    return (
      this.updateRequest.isPending ||
      this.membersRequest.isPending ||
      this.ruleRequest.isPending ||
      this.syncRequest.isPending ||
      this.deleteRequest.isPending ||
      this.orphanRequest.isPending
    );
  }

  private get target() {
    return { path: { collection_id: this.current().id } };
  }

  /** Writes that stay in Overture until the collection is synced. */
  private get localTarget() {
    return { ...this.target, query: { to_server: false } };
  }

  private async perform(action: () => Promise<void>): Promise<boolean> {
    if (this.busy) return false;
    try {
      await action();
      return true;
    } catch (error) {
      this.feedback.error(errorMessage(error, "Could not update the collection"));
      return false;
    }
  }

  /** Save in Overture; with `sync`, then make the server match. */
  save(sync = false) {
    // Read the form as it is now: the saved rule resets drafts, and saving can remount the view.
    const { target } = this;
    const options = { ...this.localTarget, body: optionsBody(this) };
    return this.perform(async () => {
      const rule = await this.persistRule();
      const saved = await this.updateRequest.mutateAsync(options);
      storeCollectionDetail(saved);
      if (rule !== undefined) patchCollectionRule(saved.id, rule);
      if (!sync) {
        this.feedback.success("Saved.");
        return;
      }
      const result = await this.syncRequest.mutateAsync(target);
      this.feedback.success(
        result.withheld
          ? "Saved. Below minimum, out of season or left out by its set, so it is off the server; Overture keeps it."
          : result.skipped
            ? "Saved. Below minimum or out of season, so the server is unchanged."
            : `Saved and synced: ${result.added} added, ${result.removed} removed.`,
      );
    });
  }

  /** Save the rule; its set decides a generated collection's, so that one is kept. */
  private async persistRule() {
    if (this.generated) return undefined;
    return this.ruleRequest.mutateAsync({ ...this.target, body: ruleBody(this) });
  }

  setMembers(memberIds: number[], order: CollectionOrder = this.collection.order_type) {
    return this.perform(async () => {
      storeCollectionDetail(
        await this.membersRequest.mutateAsync({
          ...this.localTarget,
          body: { member_ids: memberIds, order_type: order },
        }),
      );
    });
  }

  removeMember(id: number) {
    return this.setMembers(this.collection.members.filter((m) => m.id !== id).map((m) => m.id));
  }

  addMember(id: number) {
    if (this.collection.members.some((m) => m.id === id)) return Promise.resolve(false);
    return this.setMembers([...this.collection.members.map((m) => m.id), id]);
  }

  moveMember(id: number, targetIndex: number) {
    const ids = this.collection.members.map((member) => member.id);
    const fromIndex = ids.indexOf(id);
    if (
      fromIndex === -1 ||
      targetIndex < 0 ||
      targetIndex >= ids.length ||
      fromIndex === targetIndex
    ) {
      return Promise.resolve(false);
    }
    ids.splice(fromIndex, 1);
    ids.splice(targetIndex, 0, id);
    return this.setMembers(ids, "custom");
  }

  /** Why Overture cannot stop managing it, or null when it can. */
  get orphanBlocker(): string | null {
    if (this.collection.withheld) return "It is not on the media server; delete it instead";
    if (this.generated) return "Its group's set made it; remove its value from the set";
    return null;
  }

  /** Stop managing it; the server keeps it, and it moves to Unmanaged. */
  async orphan() {
    if (
      this.orphanBlocker ||
      !(await confirmAction({
        title: "Orphan collection?",
        message: `Overture forgets the criteria, group and schedule of ${this.collection.title} and lists it under Unmanaged. The media server keeps it as it is now; adopt it again to manage it.`,
        confirmLabel: "Orphan",
      }))
    )
      return;
    // Storing the orphaned collection remounts the view that owns this editor.
    const { title } = this.collection;
    await this.perform(async () => {
      storeCollectionDetail(await this.orphanRequest.mutateAsync(this.target));
      this.feedback.success(`${title} is no longer managed by Overture.`);
    });
  }

  async delete() {
    const target = await chooseAction<
      NonNullable<NonNullable<DeleteCollectionData["query"]>["target"]>
    >({
      title: "Delete collection?",
      message: `Choose where to delete ${this.collection.title}. Media files are always kept.`,
      confirmLabel: "Delete",
      destructive: true,
      choices: [
        {
          value: "server",
          label: "From the media server only",
          description:
            "Overture keeps its configuration, so a later manual or scheduled sync can recreate it.",
          unavailable: this.collection.withheld ? "It is not on the media server." : undefined,
        },
        { value: "both", label: "From Overture and the media server" },
      ],
    });
    if (!target) return;
    await this.perform(async () => {
      await this.deleteRequest.mutateAsync({ ...this.target, query: { target } });
      if (target === "both") goToCollectionsList();
    });
  }
}

/** An unsaved collection or collection set, created when its form is submitted. */
export class CollectionDraft {
  readonly defaults;
  readonly options = new Capabilities();
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
  private readonly syncGroupRequest = createMutation(() => syncCollectionGroupMutation());
  private readonly feedback = createNotifier();

  constructor(
    private readonly libraries: () => LibrarySectionRead[],
    private readonly seed: () => TmdbCollectionResponse | null,
  ) {
    this.defaults = createQuery(() =>
      getCollectionDefaultsOptions({
        query: { name: this.collectionGroup || undefined },
      }),
    );
    // Last: its query reads the form as soon as it is created.
    this.preview = new CriteriaPreview(() => this);
  }

  get serverType() {
    return settingsState.current.media_server;
  }
  get smart() {
    return !!this.rule.smart;
  }
  get libraryIds() {
    return this.rule.libraries.map((entry) => entry.library_id);
  }
  /** What the chosen libraries hold, movies first. */
  get mediaTypes(): MediaType[] {
    return heldTypes(this.libraryIds, (id) => this.typeOf(id));
  }
  get capabilities() {
    return this.options.for(this.mediaTypes[0] ?? "movie");
  }
  /** What takes requests and tags for the chosen libraries. */
  get arr() {
    return arrName(this);
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
  fieldsFor(mediaType: MediaType) {
    return availableFields(this.options.for(mediaType).data, this.smart);
  }
  get orders() {
    return availableOrders(this.options.shared(this.mediaTypes), this.smart);
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
    return this.request.isPending || this.groupRequest.isPending || this.syncGroupRequest.isPending;
  }
  /** Why the form cannot be saved yet, or null when it can. */
  get blocker(): string | null {
    if (!this.libraryIds.length) return "Choose a library";
    if (this.kind === "set") return this.setGroup ? null : "Name the set's group";
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

  /** Save in Overture; with `sync`, then create it on the server. */
  async save(sync = false) {
    if (this.busy) return false;
    return this.kind === "set" ? this.saveSet(sync) : this.saveCollection(sync);
  }

  private async saveCollection(sync: boolean) {
    try {
      const collection = await this.request.mutateAsync({
        query: { to_server: sync },
        body: { ...optionsBody(this), rule: ruleBody(this) },
      });
      storeCollectionDetail(collection);
      goToCollection(collection);
      return true;
    } catch (error) {
      this.feedback.error(errorMessage(error, "Could not save the collection"));
      return false;
    }
  }

  /** Save the set into its group, keeping the group's other defaults; `sync` runs it. */
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
        query,
        body: {
          ...existing,
          ...chosen,
          generator: { ...$state.snapshot(this.generator), library_ids: this.libraryIds },
        },
      });
      queryClient.setQueryData(getCollectionGroupPolicyOptions({ query }).queryKey, saved);
      if (!sync) {
        this.feedback.success(`Saved "${name}". Sync the group to create its collections.`);
        goToCollectionsList(name);
        return true;
      }
      const result = await this.syncGroupRequest.mutateAsync({ query });
      const errors = Object.entries(result.errors);
      if (errors.length) {
        this.feedback.error(
          `Created ${result.created.length} collections. ${errors.length} failed: ${errors
            .map(([title, error]) => `${title}: ${error}`)
            .join("; ")}`,
        );
      } else {
        this.feedback.success(`Created ${result.created.length} collections in "${name}".`);
      }
      goToCollectionsList(name);
      return true;
    } catch (error) {
      this.feedback.error(errorMessage(error, "Could not save the set"));
      return false;
    }
  }
}

/**
 * Shows what a form's criteria select now, before anything is saved, and
 * which collection kind suits them as they are edited.
 */
export class CriteriaPreview {
  private readonly request = createMutation(() => previewCollectionMutation());
  private readonly kind;

  constructor(private readonly form: () => CollectionForm) {
    this.kind = createQuery(() => {
      const { libraries } = form().rule;
      return {
        ...recommendCollectionKindOptions({ body: { rule: ruleBody(form()) } }),
        enabled:
          !!form().capabilities.data?.smart &&
          libraries.length > 0 &&
          libraries.every(
            ({ criteria }) =>
              (criteria.conditions?.length ?? 0) + (criteria.groups?.length ?? 0) > 0,
          ),
        // An unfinished condition is refused; the last advice stands until it is complete.
        placeholderData: keepPreviousData,
      };
    });
  }

  /** The kind the criteria suit, on servers with smart collections. */
  get recommendation() {
    return this.kind.data ?? null;
  }

  /** What one library's criteria selected when last previewed. */
  resultFor(libraryId: string) {
    return this.request.data?.libraries.find((entry) => entry.library_id === libraryId);
  }
  get pending() {
    return this.request.isPending;
  }
  get error() {
    return this.request.error;
  }

  run() {
    const form = this.form();
    this.request.mutate({
      body: { rule: { ...ruleBody(form), limit: form.rule.limit ?? null } },
    });
  }
}

/** The rule settings a collection keeps; Default leaves them null. */
const RULE_POLICY = [
  "sync_mode",
  "minimum_items",
  "delete_below_minimum",
  "auto_match_art",
  "auto_match_theme",
  "request_missing",
  "member_label",
  "arr_tag",
  "home_order",
] as const satisfies readonly (keyof CollectionRuleWriteInput)[];
type RulePolicy = Pick<CollectionRuleWriteInput, (typeof RULE_POLICY)[number]>;

/**
 * A form's settings as the settings fields edit them at every level. Display
 * choices belong to the collection as well as its rule, so they live on the
 * form; the rest are the rule's.
 */
export function formPolicy(form: CollectionForm) {
  const rule: RulePolicy = {};
  for (const key of RULE_POLICY) {
    Object.defineProperty(rule, key, {
      enumerable: true,
      get: () => form.rule[key],
      set: (value: RulePolicy[typeof key]) => {
        Object.assign(form.rule, { [key]: value ?? null });
      },
    });
  }
  return Object.defineProperties(rule, {
    order_type: {
      get: () => form.orderType,
      set: (value: CollectionOrder | null | undefined) => (form.orderType = value ?? null),
    },
    collection_mode: {
      get: () => form.collectionMode,
      set: (value: CollectionMode | null | undefined) => (form.collectionMode = value ?? null),
    },
    collection_filtering: {
      get: () => form.collectionFiltering,
      set: (value: CollectionFiltering | null | undefined) =>
        (form.collectionFiltering = value ?? null),
    },
    visible_home: {
      get: () => form.visibleHome,
      set: (value: boolean | null | undefined) => (form.visibleHome = value ?? null),
    },
    visible_shared: {
      get: () => form.visibleShared,
      set: (value: boolean | null | undefined) => (form.visibleShared = value ?? null),
    },
    visible_library: {
      get: () => form.visibleLibrary,
      set: (value: boolean | null | undefined) => (form.visibleLibrary = value ?? null),
    },
    sort_title_format: {
      get: () => form.sortTitleFormat || null,
      set: (value: string | null | undefined) => (form.sortTitleFormat = value ?? ""),
    },
    summary_format: {
      get: () => form.summaryFormat || null,
      set: (value: string | null | undefined) => (form.summaryFormat = value ?? ""),
    },
    active_start_mmdd: {
      get: () => form.activeStartMmdd || null,
      set: (value: string | null | undefined) => (form.activeStartMmdd = value ?? ""),
    },
    active_end_mmdd: {
      get: () => form.activeEndMmdd || null,
      set: (value: string | null | undefined) => (form.activeEndMmdd = value ?? ""),
    },
    delete_when_inactive: {
      get: () => form.deleteWhenInactive,
      set: (value: boolean | null | undefined) => (form.deleteWhenInactive = value ?? null),
    },
    // Object.defineProperties types only its target, not the accessors it adds.
  }) as RulePolicy & PolicyData & ScheduleData;
}
