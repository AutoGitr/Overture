import { createMutation, createQuery } from "@tanstack/svelte-query";
import { SvelteSet } from "svelte/reactivity";
import {
  createCollectionMutation,
  deleteCollectionMutation,
  deleteCollectionPresetMutation,
  deleteCollectionRuleMutation,
  getCollectionCapabilitiesOptions,
  getCollectionDefaultsOptions,
  getCollectionGroupPolicyOptions,
  listCollectionPresetsOptions,
  previewCollectionMutation,
  saveCollectionPresetMutation,
  saveCollectionGroupPolicyMutation,
  saveCollectionRuleMutation,
  setCollectionMembersMutation,
  syncCollectionGroupMutation,
  syncCollectionMutation,
  updateCollectionMutation,
} from "../../generated/rest/@tanstack/svelte-query.gen";
import type {
  CollectionDetail,
  CollectionFiltering,
  CollectionGeneratorInput,
  CollectionMode,
  CollectionOptions,
  CollectionGroupPolicyInput,
  CollectionOrder,
  CollectionPresetRead,
  CollectionPresetSave,
  CollectionRuleWriteInput,
  FilterGroupInput,
  LibrarySectionRead,
  MediaItemRead,
  MediaType,
  TmdbCollectionResponse,
} from "../../generated/rest/types.gen";
import {
  patchCollectionRule,
  refreshCollectionPresets,
  storeCollectionDetail,
} from "../rest/cache";
import type { PolicyData } from "../components/CollectionPolicyFields.svelte";
import type { ScheduleData } from "../components/CollectionScheduleFields.svelte";
import { queryClient } from "../rest/queryClient";
import { goToCollection, goToCollectionsList } from "../router/routes";
import { confirmAction, createNotifier } from "../stores/notificationState.svelte";
import { settingsState } from "../stores/settingsState.svelte";
import {
  availableFields,
  availableOrders,
  emptyGroup,
  franchiseCriteria,
} from "./collectionCriteria";
import { errorMessage } from "./errors";

/** Whether a collection's members are chosen by hand or by criteria. */
export type CollectionContent = "manual" | "criteria";
/** What a new collection form creates. */
export type DraftKind = "collection" | "set";

export function defaultRule(): CollectionRuleWriteInput {
  return {
    criteria: emptyGroup(),
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
    sync_schedule: null,
    sync_enabled: null,
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
    remove_vanished: false,
  };
}

type CollectionForm = CollectionEditor | CollectionDraft;

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
    collection_group: form.collectionGroup || null,
    tmdb_collection_id: form.tmdbCollectionId ?? null,
    collection_mode: form.collectionMode,
    ...(form.orderType === null ? {} : { order_type: form.orderType }),
    ...(form.visibleHome === null ? {} : { visible_home: form.visibleHome }),
    ...(form.visibleShared === null ? {} : { visible_shared: form.visibleShared }),
    ...(form.visibleLibrary === null ? {} : { visible_library: form.visibleLibrary }),
  };
}

function capabilitiesQuery(mediaType: () => MediaType) {
  return createQuery(() => ({
    ...getCollectionCapabilitiesOptions({ query: { media_type: mediaType() } }),
    enabled: settingsState.current.collections_supported,
  }));
}

/** Form drafts and actions for one mounted collection. */
export class CollectionEditor {
  readonly defaults;
  readonly capabilities;
  readonly creating = false;
  // Drafts reset when saved fields change, not when unrelated collection data changes.
  private savedTitle = $derived.by(() => this.current().title);
  title = $derived(this.savedTitle);
  private savedSortExpression = $derived.by(
    () =>
      this.current().sort_title_format ??
      (this.current().rule
        ? (this.current().rule?.sort_title_format ?? "")
        : (this.current().sort_title ?? "")),
  );
  sortTitleFormat = $derived(this.savedSortExpression);
  private savedGroup = $derived.by(() => this.current().collection_group);
  collectionGroup = $derived(this.savedGroup ?? "");
  private savedCollectionMode = $derived.by(() =>
    this.current().rule
      ? (this.current().rule?.collection_mode ?? null)
      : this.current().collection_mode,
  );
  collectionMode = $derived(this.savedCollectionMode);
  private savedVisibleHome = $derived.by(() =>
    this.current().rule ? (this.current().rule?.visible_home ?? null) : this.current().visible_home,
  );
  visibleHome = $derived<boolean | null>(this.savedVisibleHome);
  private savedSummaryExpression = $derived.by(
    () =>
      this.current().summary_format ??
      (this.current().rule
        ? (this.current().rule?.summary_format ?? "")
        : (this.current().summary ?? "")),
  );
  summaryFormat = $derived(this.savedSummaryExpression);
  private savedActiveStart = $derived.by(() => this.current().active_start_mmdd);
  activeStartMmdd = $derived(this.savedActiveStart ?? "");
  private savedActiveEnd = $derived.by(() => this.current().active_end_mmdd);
  activeEndMmdd = $derived(this.savedActiveEnd ?? "");
  private savedDeleteWhenInactive = $derived.by(() => this.current().delete_when_inactive);
  deleteWhenInactive = $derived(this.savedDeleteWhenInactive);
  private savedCollectionFiltering = $derived.by(() =>
    this.current().rule
      ? (this.current().rule?.collection_filtering ?? null)
      : this.current().collection_filtering,
  );
  collectionFiltering = $derived(this.savedCollectionFiltering);
  private savedVisibleShared = $derived.by(() =>
    this.current().rule
      ? (this.current().rule?.visible_shared ?? null)
      : this.current().visible_shared,
  );
  visibleShared = $derived<boolean | null>(this.savedVisibleShared);
  private savedVisibleLibrary = $derived.by(() =>
    this.current().rule
      ? (this.current().rule?.visible_library ?? null)
      : this.current().visible_library,
  );
  visibleLibrary = $derived<boolean | null>(this.savedVisibleLibrary);
  libraryId = $derived.by(() => this.current().library_id ?? "");
  private savedTmdbId = $derived.by(() => this.current().tmdb_collection_id);
  tmdbCollectionId = $derived(this.savedTmdbId ?? undefined);
  private savedOrder = $derived.by(() =>
    this.current().rule ? (this.current().rule?.order_type ?? null) : this.current().order_type,
  );
  orderType = $derived<CollectionOrder | null>(this.savedOrder);
  /** A smart collection made in Plex keeps its filter until Overture takes it over. */
  manageServerFilter = $state(false);
  content = $state<CollectionContent>("manual");
  rule = $state<CollectionRuleWriteInput>(defaultRule());

  memberSearch = $state("");
  draggingMemberId = $state<number | null>(null);
  readonly preview = new CriteriaPreview(() => this);

  private readonly updateRequest = createMutation(() => updateCollectionMutation());
  private readonly membersRequest = createMutation(() => setCollectionMembersMutation());
  private readonly ruleRequest = createMutation(() => saveCollectionRuleMutation());
  private readonly removeRuleRequest = createMutation(() => deleteCollectionRuleMutation());
  private readonly syncRequest = createMutation(() => syncCollectionMutation());
  private readonly deleteRequest = createMutation(() => deleteCollectionMutation());
  private readonly feedback = createNotifier();

  constructor(private readonly current: () => CollectionDetail) {
    this.defaults = createQuery(() =>
      getCollectionDefaultsOptions({
        query: { media_type: this.mediaType, name: this.collectionGroup || undefined },
      }),
    );
    this.capabilities = capabilitiesQuery(() => this.mediaType);
    const saved = this.current().rule;
    if (saved) {
      const {
        last_error: _error,
        last_synced_at: _synced,
        source_summary: _summary,
        ...rest
      } = saved;
      this.content = "criteria";
      this.rule = structuredClone(rest);
    } else if (this.current().kind === "smart") {
      this.content = "criteria";
      this.rule.smart = true;
    }
  }

  get collection() {
    return this.current();
  }
  get serverType() {
    return this.collection.server_type;
  }
  get mediaType() {
    return this.collection.media_type;
  }
  /** Its collection set decides the criteria and title of a generated collection. */
  get generated() {
    return this.collection.generated_value !== null;
  }
  get smart() {
    return this.content === "criteria" && !!this.rule.smart;
  }
  get fields() {
    return availableFields(this.capabilities.data, this.smart);
  }
  get orders() {
    return availableOrders(this.capabilities.data, this.smart);
  }
  /** Saving rewrites the criteria unless Plex keeps a filter Overture never saw. */
  get criteriaEditable() {
    return (
      this.content !== "criteria" ||
      this.collection.rule !== null ||
      this.collection.kind !== "smart" ||
      this.manageServerFilter
    );
  }
  get manualMembersAllowed() {
    const rule = this.collection.rule;
    return (
      this.collection.kind !== "smart" &&
      (!rule || (rule.sync_mode ?? this.collection.effective_sync_mode) === "append")
    );
  }

  availableMembers(libraryItems: MediaItemRead[]) {
    const query = this.memberSearch.trim().toLowerCase();
    if (!query) return [];
    const memberIds = new SvelteSet(this.collection.members.map((member) => member.id));
    return libraryItems.filter(
      (item) =>
        item.library_id === this.collection.library_id &&
        item.server_item_id &&
        !item.server_removed_at &&
        !memberIds.has(item.id) &&
        item.title.toLowerCase().includes(query),
    );
  }

  get busy() {
    return (
      this.updateRequest.isPending ||
      this.membersRequest.isPending ||
      this.ruleRequest.isPending ||
      this.syncRequest.isPending ||
      this.deleteRequest.isPending ||
      this.removeRuleRequest.isPending
    );
  }

  private get target() {
    const c = this.current();
    return { path: { collection_id: c.id }, query: { media_type: c.media_type } };
  }

  /** Writes that stay in Overture until the collection is synced. */
  private get localTarget() {
    return { ...this.target, query: { ...this.target.query, to_server: false } };
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
    return this.perform(async () => {
      const rule = await this.persistRule();
      const saved = await this.updateRequest.mutateAsync({
        ...this.localTarget,
        body: optionsBody(this),
      });
      storeCollectionDetail(saved);
      if (rule !== undefined) patchCollectionRule(saved.id, rule);
      if (!sync) {
        this.feedback.success("Saved.");
        return;
      }
      const result = await this.syncRequest.mutateAsync(this.target);
      if (result.deleted) goToCollectionsList(this.collection.media_type);
      this.feedback.success(
        result.skipped
          ? "Saved. Below minimum or out of season, so the server is unchanged."
          : `Saved and synced: ${result.added} added, ${result.removed} removed.`,
      );
    });
  }

  /** Save, remove or keep the rule; `undefined` when nothing changed. */
  private async persistRule() {
    if (this.generated || !this.criteriaEditable) return undefined;
    if (this.content === "manual") {
      if (!this.collection.rule) return undefined;
      await this.removeRuleRequest.mutateAsync(this.target);
      return null;
    }
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

  async delete() {
    if (
      !(await confirmAction({
        title: "Delete collection?",
        message: `Delete ${this.collection.title} from the media server? Its media files are kept.`,
        confirmLabel: "Delete",
        destructive: true,
      }))
    )
      return;
    await this.perform(async () => {
      await this.deleteRequest.mutateAsync(this.target);
      goToCollectionsList(this.collection.media_type);
    });
  }
}

/** An unsaved collection or collection set, created when its form is submitted. */
export class CollectionDraft {
  readonly defaults;
  readonly capabilities;
  readonly presets;
  readonly creating = true;
  readonly manualMembersAllowed = false;
  readonly generated = false;
  readonly criteriaEditable = true;
  kind = $state<DraftKind>("collection");
  presetKey = $state("");
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
  content = $state<CollectionContent>("criteria");
  rule = $derived.by(() => {
    const seed = this.seed();
    const rule = $state({
      ...defaultRule(),
      ...(seed ? { criteria: franchiseCriteria(seed.tmdb_id) } : {}),
    });
    return rule;
  });
  /** The group policy and generator a new set saves. */
  setPolicy = $state<SetPolicy>({});
  generator = $state<SetGenerator>(defaultGenerator());
  private onlyLibrary = $derived.by(() =>
    this.libraries().length === 1 ? [this.libraries()[0]?.id ?? ""] : [],
  );
  /** One library, or several: a collection in several libraries is kept alike in each. */
  libraryIds = $derived<string[]>(this.onlyLibrary);
  readonly preview = new CriteriaPreview(() => this);
  readonly request = createMutation(() => createCollectionMutation());
  private readonly groupRequest = createMutation(() => saveCollectionGroupPolicyMutation());
  private readonly syncGroupRequest = createMutation(() => syncCollectionGroupMutation());
  private readonly feedback = createNotifier();

  constructor(
    readonly mediaType: MediaType,
    private readonly libraries: () => LibrarySectionRead[],
    private readonly seed: () => TmdbCollectionResponse | null,
  ) {
    this.defaults = createQuery(() =>
      getCollectionDefaultsOptions({
        query: { media_type: this.mediaType, name: this.collectionGroup || undefined },
      }),
    );
    this.capabilities = capabilitiesQuery(() => this.mediaType);
    this.presets = createQuery(() =>
      listCollectionPresetsOptions({ query: { media_type: this.mediaType } }),
    );
  }

  get serverType() {
    return settingsState.current.media_server;
  }
  get smart() {
    return !!this.rule.smart;
  }
  get fields() {
    return availableFields(this.capabilities.data, this.smart);
  }
  get orders() {
    return availableOrders(this.capabilities.data, this.smart);
  }
  /** The group a set saves into: the one named, or else the dimension's name. */
  get setGroup() {
    return (
      this.collectionGroup.trim() ||
      this.capabilities.data?.dimensions.find(
        (entry) => entry.dimension === this.generator.dimension,
      )?.label ||
      ""
    );
  }
  get busy() {
    return this.request.isPending || this.groupRequest.isPending || this.syncGroupRequest.isPending;
  }
  /** The library criteria suggest values from and previews count in. */
  get libraryId() {
    return this.libraryIds[0] ?? "";
  }
  /** A collection in several libraries saves as a set with one collection in each. */
  get linked() {
    return this.kind === "collection" && this.libraryIds.length > 1;
  }
  get canSubmit() {
    if (!this.libraryIds.length) return false;
    if (this.kind === "set") return !!this.setGroup;
    return !!this.title.trim();
  }

  selectKind(kind: DraftKind) {
    this.kind = kind;
    this.presetKey = "";
  }

  /** Start from a preset of either kind: it fills the form, which stays editable. */
  applyPreset(preset: CollectionPresetRead | undefined) {
    this.presetKey = preset?.key ?? "";
    if (preset) this.kind = preset.set ? "set" : "collection";
    if (preset?.collection) {
      const saved = preset.collection.rule;
      this.title = preset.collection.title;
      this.collectionFiltering = preset.collection.collection_filtering;
      this.orderType = saved.order_type;
      this.sortTitleFormat = saved.sort_title_format ?? "";
      this.summaryFormat = saved.summary_format ?? "";
      this.activeStartMmdd = saved.active_start_mmdd ?? "";
      this.activeEndMmdd = saved.active_end_mmdd ?? "";
      this.deleteWhenInactive = saved.delete_when_inactive;
      // A writable derived holds what it is given, so the copy is made deeply reactive.
      const rule = $state({ ...defaultRule(), ...structuredClone(saved) });
      this.rule = rule;
    } else if (preset?.set) {
      this.collectionGroup = preset.set.group;
      this.setPolicy = structuredClone(preset.set.policy);
      this.generator = {
        ...defaultGenerator(this.libraryIds),
        ...structuredClone(preset.set.generator),
      };
    }
  }

  /** Save in Overture; with `sync`, then create it on the server. */
  async save(sync = false) {
    if (this.busy) return false;
    return this.kind === "set" ? this.saveSet(sync) : this.saveCollection(sync);
  }

  private async saveCollection(sync: boolean) {
    if (this.linked) {
      const rule = presetRule(this);
      const { criteria, smart, limit: _limit, ...policy } = rule;
      return this.saveSet(sync, {
        group: this.collectionGroup.trim() || this.title.trim(),
        policy,
        generator: {
          ...defaultGenerator(this.libraryIds),
          dimension: "custom",
          title_format: "{value}",
          smart,
          custom_values: [{ name: this.title.trim(), criteria }],
        },
      });
    }
    try {
      const collection = await this.request.mutateAsync({
        query: { to_server: sync },
        body: {
          ...optionsBody(this),
          media_type: this.mediaType,
          library_id: this.libraryId,
          member_ids: [],
          rule: ruleBody(this),
        },
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
  private async saveSet(
    sync: boolean,
    set: { group: string; policy: SetPolicy; generator: SetGenerator } = {
      group: this.setGroup,
      policy: this.setPolicy,
      generator: this.generator,
    },
  ) {
    const name = set.group;
    const query = { name, media_type: this.mediaType };
    try {
      const existing = await queryClient.fetchQuery(getCollectionGroupPolicyOptions({ query }));
      // A choice left at Default keeps what an existing group already has.
      const chosen = Object.fromEntries(
        Object.entries($state.snapshot(set.policy)).filter(([, value]) => value !== null),
      );
      const saved = await this.groupRequest.mutateAsync({
        query,
        body: {
          ...existing,
          ...chosen,
          generator: { ...$state.snapshot(set.generator), library_ids: this.libraryIds },
        },
      });
      queryClient.setQueryData(getCollectionGroupPolicyOptions({ query }).queryKey, saved);
      if (!sync) {
        this.feedback.success(`Saved "${name}". Sync the group to create its collections.`);
        goToCollectionsList(this.mediaType, name);
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
      goToCollectionsList(this.mediaType, name);
      return true;
    } catch (error) {
      this.feedback.error(errorMessage(error, "Could not save the set"));
      return false;
    }
  }
}

/** The rule a preset or a linked set keeps: criteria with every chosen setting. */
function presetRule(form: CollectionForm): CollectionRuleWriteInput {
  return {
    ...ruleBody(form),
    sort_title_format: form.sortTitleFormat || null,
    summary_format: form.summaryFormat || null,
    active_start_mmdd: form.activeStartMmdd || null,
    active_end_mmdd: form.activeEndMmdd || null,
    delete_when_inactive: form.deleteWhenInactive,
  };
}

/** What a form keeps as a preset: its collection, or its set. */
export function presetBody(form: CollectionForm, label: string): CollectionPresetSave {
  const base = { media_type: form.mediaType, label: label.trim() };
  if (form instanceof CollectionDraft && form.kind === "set") {
    const { library_ids: _libraries, ...generator } = $state.snapshot(form.generator);
    return {
      ...base,
      set: { group: form.setGroup, policy: $state.snapshot(form.setPolicy), generator },
    };
  }
  return {
    ...base,
    collection: {
      title: form.title.trim(),
      collection_filtering: form.collectionFiltering,
      rule: presetRule(form),
    },
  };
}

/** Saves a form as a preset, and forgets saved ones. */
export class PresetActions {
  private readonly saveRequest = createMutation(() => saveCollectionPresetMutation());
  private readonly deleteRequest = createMutation(() => deleteCollectionPresetMutation());
  private readonly feedback = createNotifier();
  label = $state("");

  constructor(private readonly form: () => CollectionForm) {}

  get busy() {
    return this.saveRequest.isPending || this.deleteRequest.isPending;
  }

  async save() {
    if (this.busy || !this.label.trim()) return;
    try {
      const saved = await this.saveRequest.mutateAsync({
        body: presetBody(this.form(), this.label),
      });
      await refreshCollectionPresets();
      this.feedback.success(`Saved the preset "${saved.label}".`);
      this.label = "";
    } catch (error) {
      this.feedback.error(errorMessage(error, "Could not save the preset"));
    }
  }

  async delete(preset: CollectionPresetRead) {
    if (this.busy || preset.saved_id == null) return;
    try {
      await this.deleteRequest.mutateAsync({ path: { preset_id: preset.saved_id } });
      await refreshCollectionPresets();
    } catch (error) {
      this.feedback.error(errorMessage(error, "Could not delete the preset"));
    }
  }
}

/** Shows what a form's criteria select now, before anything is saved. */
export class CriteriaPreview {
  private readonly request = createMutation(() => previewCollectionMutation());

  constructor(private readonly form: () => CollectionForm) {}

  get result() {
    return this.request.data;
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
      body: {
        media_type: form.mediaType,
        library_id: form.libraryId,
        rule: { ...ruleBody(form), limit: form.rule.limit ?? null },
      },
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
  "sync_schedule",
  "sync_enabled",
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
