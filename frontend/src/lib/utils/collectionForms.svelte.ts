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
  private savedRule = $derived.by(() => this.current().rule);

  sourceType: RuleSourceType | "manual" = $derived(this.savedRule?.source_type ?? "manual");

  rule: CollectionRuleWrite = $derived.by(() => {
    const rule = this.savedRule;
    const { last_error: _error, last_synced_at: _synced, ...saved } = rule ?? {};
    const draft = $state<CollectionRuleWrite>(
      rule
        ? { ...saved, source_type: rule.source_type, filters: { ...rule.filters } }
        : {
            source_type: "mdblist",
            source_identifier: "",
            filters: {},
            sync_mode: null,
            minimum_items: null,
            delete_below_minimum: null,
            enabled: true,
            sync_interval_hours: 24,
          },
    );
    return draft;
  });

  memberSearch = $state("");
  draggingMemberId = $state<number | null>(null);

  get manualMembersAllowed() {
    const rule = this.collection.rule;
    return !rule || (rule.sync_mode ?? settingsState.current.collection_sync_mode) === "append";
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
        body: {
          title: this.title,
          summary: this.summary,
          sort_title: this.sortTitle,
          collection_group: this.collectionGroup || null,
          collection_mode: this.collectionMode,
          order_type: this.collection.order_type,
          visible_home: this.visibleHome,
        },
      });
      storeCollectionDetail(saved);
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
export class CollectionCreation {
  title = $state("");
  libraryId = $state("");
  readonly memberIds = new SvelteSet<number>();
  search = $state("");
  preset: CollectionPreset = $state("decades");
  readonly titles = new SvelteSet<string>();

  readonly preview = createMutation(() => previewCollectionGeneratorMutation());
  readonly generateRequest = createMutation(() => generateCollectionsMutation());
  readonly createRequest = createMutation(() => createCollectionMutation());
  private readonly feedback = createNotifier();

  constructor(readonly mediaType: MediaType) {}

  get body() {
    return {
      media_type: this.mediaType,
      library_id: this.libraryId,
      preset: this.preset,
      titles: Array.from(this.titles),
    };
  }

  resetPreview() {
    this.preview.reset();
    this.titles.clear();
  }

  toggle(id: number) {
    if (!this.memberIds.delete(id)) {
      this.memberIds.add(id);
    }
  }

  toggleTitle(title: string) {
    if (!this.titles.delete(title)) {
      this.titles.add(title);
    }
  }

  async create(): Promise<boolean> {
    try {
      const collection = await this.createRequest.mutateAsync({
        body: {
          title: this.title.trim(),
          library_id: this.libraryId,
          media_type: this.mediaType,
          member_ids: Array.from(this.memberIds),
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
