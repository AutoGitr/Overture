import { createMutation } from "@tanstack/svelte-query";
import { SvelteSet } from "svelte/reactivity";
import {
  createCollectionMutation,
  deleteCollectionMutation,
  deleteCollectionRuleMutation,
  generateCollectionsMutation,
  previewCollectionGeneratorMutation,
  saveCollectionRuleMutation,
  setCollectionMembersMutation,
  syncCollectionRuleMutation,
  updateCollectionMutation,
} from "../../generated/rest/@tanstack/svelte-query.gen";
import type {
  CollectionDetail,
  CollectionOrder,
  CollectionPreset,
  CollectionRuleWrite,
  MediaType,
  MediaItemRead,
  RuleSourceType,
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
  private savedRule = $derived.by(() => this.current().rule);

  sourceType: RuleSourceType | "manual" = $derived(this.savedRule?.source_type ?? "manual");

  rule: CollectionRuleWrite = $derived.by(() => {
    const rule = this.savedRule;
    const { last_error: _error, last_synced_at: _synced, ...saved } = rule ?? {};
    const draft = $state<CollectionRuleWrite>(
      rule
        ? { ...saved, source_type: rule.source_type, filters: { ...rule.filters } }
        : defaultCollectionRule(),
    );
    return draft;
  });

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

  constructor(private readonly current: () => CollectionDetail) {}

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

  private async persistRule(source: RuleSourceType | "manual", draft: CollectionRuleWrite) {
    const target = this.target;
    if (source === "manual") {
      if (this.collection.rule) {
        await this.removeRuleRequest.mutateAsync(target);
      }
      return null;
    }
    const savedRule = await this.ruleRequest.mutateAsync({
      ...target,
      body: { ...draft, source_type: source },
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

/** Creation and generator drafts; network results stay in mutation observers. */
export class CollectionGenerator {
  libraryId = $derived.by(() => this.defaultLibrary());
  collectionGroup = $state("");
  sync_mode = $state<CollectionRuleWrite["sync_mode"]>(null);
  minimum_items = $state<number | null>(null);
  delete_below_minimum = $state<boolean | null>(null);
  auto_match_art = $state<boolean | null>(null);
  auto_match_theme = $state<boolean | null>(null);
  collection_mode = $state<CollectionMode | null>(null);
  sort_title_format = $state("");
  preset: CollectionPreset = $state("decades");
  readonly titles = new SvelteSet<string>();

  readonly preview = createMutation(() => previewCollectionGeneratorMutation());
  readonly generateRequest = createMutation(() => generateCollectionsMutation());
  private readonly feedback = createNotifier();

  constructor(
    readonly mediaType: MediaType,
    private readonly defaultLibrary: () => string = () => "",
  ) {}

  get body() {
    return {
      media_type: this.mediaType,
      library_id: this.libraryId,
      preset: this.preset,
      collection_group: this.collectionGroup || null,
      sync_mode: this.sync_mode,
      minimum_items: this.minimum_items,
      delete_below_minimum: this.delete_below_minimum,
      auto_match_art: this.auto_match_art,
      auto_match_theme: this.auto_match_theme,
      collection_mode: this.collection_mode,
      sort_title_format: this.sort_title_format || null,
      titles: Array.from(this.titles),
    };
  }

  resetPreview() {
    this.preview.reset();
    this.titles.clear();
  }

  toggleTitle(title: string) {
    if (!this.titles.delete(title)) {
      this.titles.add(title);
    }
  }

  async previewCollections() {
    this.titles.clear();
    try {
      await this.preview.mutateAsync({ body: this.body });
    } catch (error) {
      this.feedback.error(errorMessage(error, "Preview failed"));
    }
  }

  async generate(): Promise<boolean> {
    try {
      const result = await this.generateRequest.mutateAsync({ body: this.body });
      this.feedback.success(`${result.created.length} collections created.`);
      for (const [title, error] of Object.entries(result.errors))
        this.feedback.error(`${title}: ${error}`);
      return Object.keys(result.errors).length === 0;
    } catch (error) {
      this.feedback.error(errorMessage(error, "Generation failed"));
      return false;
    }
  }
}

function defaultCollectionRule(identifier = ""): CollectionRuleWrite {
  return {
    source_type: "mdblist",
    source_identifier: identifier,
    filters: {},
    sync_mode: null,
    minimum_items: null,
    delete_below_minimum: null,
    auto_match_art: null,
    auto_match_theme: null,
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
    collection_group: form.collectionGroup || null,
    tmdb_collection_id: form.tmdbCollectionId ?? null,
    collection_mode: form.collectionMode,
    order_type: form.orderType,
    visible_home: form.visibleHome,
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
  private onlyLibrary = $derived.by(() =>
    this.libraries().length === 1 ? (this.libraries()[0]?.id ?? "") : "",
  );
  libraryId = $derived(this.onlyLibrary);
  sourceType: RuleSourceType | "manual" = $derived.by(() => (this.seed() ? "tmdb" : "manual"));
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
          rule:
            this.sourceType === "manual"
              ? null
              : { ...$state.snapshot(this.rule), source_type: this.sourceType },
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
