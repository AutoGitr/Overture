import { createMutation } from "@tanstack/svelte-query";
import { SvelteSet } from "svelte/reactivity";
import {
  createCollectionMutation,
  deleteCollectionMutation,
  deleteCollectionRuleMutation,
  saveCollectionRuleMutation,
  setCollectionMembersMutation,
  syncCollectionRuleMutation,
  updateCollectionMutation,
} from "../../generated/rest/@tanstack/svelte-query.gen";
import type {
  CollectionDetail,
  CollectionFiltering,
  CollectionKind,
  CollectionOrder,
  CollectionRuleWrite,
  MediaType,
  MediaItemRead,
  CollectionMode,
  CollectionOptions,
  LibrarySectionRead,
  TmdbCollectionResponse,
} from "../../generated/rest/types.gen";
import { patchCollectionRule, storeCollectionDetail } from "../rest/cache";
import { goToCollection, goToCollectionsList } from "../router/routes";
import { settingsState } from "../stores/settingsState.svelte";
import { confirmAction, createNotifier } from "../stores/notificationState.svelte";
import { errorMessage } from "./errors";

export type RuleEditorSource = "manual" | "builders" | "smart";

/** Form drafts and actions for one mounted collection. */
export class CollectionEditor {
  // Drafts reset when saved fields change, not when unrelated collection data changes.
  private savedTitle = $derived.by(() => this.current().title);
  title = $derived(this.savedTitle);
  sortTitleFormat = $state("");
  private savedSummary = $derived.by(() => this.current().summary);
  summary = $derived(this.savedSummary);
  private savedSortTitle = $derived.by(() => this.current().sort_title);
  sortTitle = $derived(this.savedSortTitle);
  private savedGroup = $derived.by(() => this.current().collection_group);
  collectionGroup = $derived(this.savedGroup ?? "");
  private savedCollectionMode = $derived.by(() => this.current().collection_mode);
  collectionMode = $derived(this.savedCollectionMode);
  private savedVisibleHome = $derived.by(() => this.current().visible_home);
  visibleHome = $derived(this.savedVisibleHome);
  private savedKind = $derived.by(() => this.current().kind);
  kind = $derived(this.savedKind);
  private savedSummaryFormat = $derived.by(() => this.current().summary_format);
  summaryFormat = $derived(this.savedSummaryFormat ?? "");
  private savedActiveStart = $derived.by(() => this.current().active_start_mmdd);
  activeStartMmdd = $derived(this.savedActiveStart ?? "");
  private savedActiveEnd = $derived.by(() => this.current().active_end_mmdd);
  activeEndMmdd = $derived(this.savedActiveEnd ?? "");
  private savedDeleteWhenInactive = $derived.by(() => this.current().delete_when_inactive);
  deleteWhenInactive = $derived(this.savedDeleteWhenInactive);
  private savedCollectionFiltering = $derived.by(() => this.current().collection_filtering);
  collectionFiltering = $derived(this.savedCollectionFiltering);
  private savedVisibleShared = $derived.by(() => this.current().visible_shared);
  visibleShared = $derived(this.savedVisibleShared);
  private savedVisibleLibrary = $derived.by(() => this.current().visible_library);
  visibleLibrary = $derived(this.savedVisibleLibrary);
  libraryId = $derived.by(() => this.current().library_id ?? "");
  private savedTmdbId = $derived.by(() => this.current().tmdb_collection_id);
  tmdbCollectionId = $derived(this.savedTmdbId ?? undefined);
  readonly creating = false;
  get serverType() {
    return this.collection.server_type;
  }
  get mediaType() {
    return this.collection.media_type;
  }
  get existingRule() {
    return this.collection.rule;
  }
  get orderType() {
    return this.collection.order_type;
  }
  sourceType = $state<RuleEditorSource>("manual");
  rule = $state<CollectionRuleWrite>(defaultCollectionRule());

  memberSearch = $state("");
  draggingMemberId = $state<number | null>(null);

  get manualMembersAllowed() {
    const rule = this.collection.rule;
    return !rule || (rule.sync_mode ?? this.collection.effective_sync_mode) === "append";
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

  private readonly updateRequest = createMutation(() => updateCollectionMutation());
  private readonly membersRequest = createMutation(() => setCollectionMembersMutation());
  private readonly ruleRequest = createMutation(() => saveCollectionRuleMutation());
  private readonly removeRuleRequest = createMutation(() => deleteCollectionRuleMutation());
  private readonly syncRequest = createMutation(() => syncCollectionRuleMutation());
  private readonly deleteRequest = createMutation(() => deleteCollectionMutation());
  private readonly feedback = createNotifier();

  constructor(private readonly current: () => CollectionDetail) {
    const saved = this.current().rule;
    if (saved) {
      this.sourceType = saved.smart_filter ? "smart" : "builders";
      const { last_error: _error, last_synced_at: _synced, ...rest } = saved;
      this.rule = {
        ...rest,
        builders: saved.builders ? JSON.parse(JSON.stringify(saved.builders)) : [],
        smart_filter: saved.smart_filter ? JSON.parse(JSON.stringify(saved.smart_filter)) : null,
      };
    }
  }

  get collection() {
    return this.current();
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

  private async perform(action: () => Promise<void>): Promise<boolean> {
    if (this.busy) return false;
    try {
      await action();
      return true;
    } catch (error) {
      this.feedback.error(errorMessage(error, "Collection update failed"));
      return false;
    }
  }

  save() {
    return this.perform(async () => {
      const source = this.sourceType;
      const draft = $state.snapshot(this.rule);
      const saved = await this.updateRequest.mutateAsync({
        ...this.target,
        body: collectionOptions(this),
      });
      storeCollectionDetail(saved);
      this.sortTitleFormat = "";
      const rule = await this.persistRule(source, draft);
      patchCollectionRule(saved.id, rule);
      this.feedback.success("Collection changes saved.");
    });
  }

  setMembers(memberIds: number[], order: CollectionOrder = this.collection.order_type) {
    return this.perform(async () => {
      storeCollectionDetail(
        await this.membersRequest.mutateAsync({
          ...this.target,
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

  private async persistRule(source: RuleEditorSource, draft: CollectionRuleWrite) {
    const target = this.target;
    if (source === "manual") {
      if (this.collection.rule) {
        await this.removeRuleRequest.mutateAsync(target);
      }
      return null;
    }
    const savedRule = await this.ruleRequest.mutateAsync({
      ...target,
      body: draft,
    });
    return savedRule;
  }

  sync() {
    return this.perform(async () => {
      const result = await this.syncRequest.mutateAsync(this.target);
      if (result.deleted) {
        goToCollectionsList(this.collection.media_type);
      }
      this.feedback.success(
        result.skipped
          ? "Below minimum; membership kept."
          : `Synced: ${result.added} added, ${result.removed} removed.`,
      );
    });
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

function defaultCollectionRule(identifier = ""): CollectionRuleWrite {
  return {
    builders: identifier ? [{ type: "tmdb_collection", collection_id: Number(identifier) }] : [],
    smart_filter: null,
    managed_label: null,
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
    enabled: true,
    sync_interval_hours: 24,
  };
}

function collectionOptions(form: CollectionEditor | CollectionDraft): CollectionOptions {
  return {
    title: form.title.trim(),
    summary: form.summary,
    sort_title: form.sortTitle,
    sort_title_format: form.sortTitleFormat || null,
    summary_format: form.summaryFormat || null,
    active_start_mmdd: form.activeStartMmdd || null,
    active_end_mmdd: form.activeEndMmdd || null,
    delete_when_inactive: form.deleteWhenInactive,
    collection_filtering: form.collectionFiltering,
    kind: form.sourceType === "smart" ? "smart" : form.kind,
    collection_group: form.collectionGroup || null,
    tmdb_collection_id: form.tmdbCollectionId ?? null,
    collection_mode: form.collectionMode,
    order_type: form.orderType,
    visible_home: form.visibleHome,
    visible_shared: form.visibleShared,
    visible_library: form.visibleLibrary,
  };
}

/** An unsaved collection, created only after its Configure form is submitted. */
export class CollectionDraft {
  readonly creating = true;
  sortTitleFormat = $state("");
  title = $derived.by(() => this.seed()?.title ?? "");
  summary = $state<string | null>(null);
  sortTitle = $state<string | null>(null);
  collectionGroup = $state("");
  tmdbCollectionId = $derived.by(() => this.seed()?.tmdb_id);
  collectionMode = $state<CollectionMode | null>(null);
  visibleHome = $state(false);
  kind = $state<CollectionKind>("regular");
  summaryFormat = $state("");
  activeStartMmdd = $state("");
  activeEndMmdd = $state("");
  deleteWhenInactive = $state<boolean | null>(null);
  collectionFiltering = $state<CollectionFiltering | null>(null);
  visibleShared = $state(false);
  visibleLibrary = $state(false);
  private onlyLibrary = $derived.by(() =>
    this.libraries().length === 1 ? (this.libraries()[0]?.id ?? "") : "",
  );
  libraryId = $derived(this.onlyLibrary);
  sourceType: RuleEditorSource = $derived.by(() => (this.seed() ? "builders" : "manual"));
  rule = $derived.by(() => {
    const seed = this.seed();
    const draft = $state(defaultCollectionRule(seed ? String(seed.tmdb_id) : ""));
    return draft;
  });
  orderType = $state<CollectionOrder>("release");
  readonly memberIds = new SvelteSet<number>();
  memberSearch = $state("");
  readonly request = createMutation(() => createCollectionMutation());
  private readonly feedback = createNotifier();

  constructor(
    readonly mediaType: MediaType,
    private readonly libraries: () => LibrarySectionRead[],
    private readonly seed: () => TmdbCollectionResponse | null,
  ) {}
  get serverType() {
    return settingsState.current.media_server;
  }
  get existingRule() {
    return null;
  }
  get busy() {
    return this.request.isPending;
  }
  get canSubmit() {
    return (
      !!this.libraryId &&
      !!this.title.trim() &&
      (this.sourceType !== "manual" || this.memberIds.size > 0)
    );
  }
  get manualMembersAllowed() {
    return (
      this.sourceType === "manual" ||
      (this.rule.sync_mode ?? settingsState.current.collection_sync_mode) === "append"
    );
  }

  selectLibrary(id: string) {
    this.libraryId = id;
    this.memberIds.clear();
  }
  availableMembers(items: MediaItemRead[]) {
    const query = this.memberSearch.trim().toLowerCase();
    return items.filter(
      (item) =>
        item.library_id === this.libraryId &&
        item.server_item_id &&
        !item.server_removed_at &&
        item.title.toLowerCase().includes(query),
    );
  }
  toggle(id: number) {
    if (!this.memberIds.delete(id)) this.memberIds.add(id);
  }

  async save() {
    if (this.busy) return false;
    try {
      const collection = await this.request.mutateAsync({
        body: {
          ...collectionOptions(this),
          media_type: this.mediaType,
          library_id: this.libraryId,
          member_ids: [...this.memberIds],
          rule: this.sourceType === "manual" ? null : $state.snapshot(this.rule),
        },
      });
      storeCollectionDetail(collection);
      goToCollection(collection);
      return true;
    } catch (error) {
      this.feedback.error(errorMessage(error, "Collection creation failed"));
      return false;
    }
  }
}
