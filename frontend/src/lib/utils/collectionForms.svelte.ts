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
  CollectionOptions,
  CollectionOrder,
  CollectionPreset,
  CollectionRuleWrite,
  MediaType,
} from "../../generated/rest/types.gen";
import { patchCollectionRule, storeCollectionDetail } from "../rest/cache";
import { goToCollection, goToCollectionsList } from "../router/routes";
import { confirmAction, createNotifier } from "../stores/notificationState.svelte";
import { errorMessage } from "./errors";

/** Form drafts and actions for one mounted collection. */
export class CollectionEditor {
  options: CollectionOptions = $derived.by(() => {
    const collection = this.current();
    const draft = $state<CollectionOptions>({
      title: collection.title,
      summary: collection.summary,
      sort_title: collection.sort_title,
      collection_mode: collection.collection_mode,
      order_type: collection.order_type,
      visible_home: collection.visible_home,
    });
    return draft;
  });

  rule: CollectionRuleWrite = $derived.by(() => {
    const rule = this.current().rule;
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
      storeCollectionDetail(
        await this.updateRequest.mutateAsync({ ...this.target, body: this.options }),
      );
      this.feedback.success("Collection settings saved.");
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

  saveRule() {
    return this.perform(async () => {
      const target = this.target;
      const savedRule = await this.ruleRequest.mutateAsync({ ...target, body: this.rule });
      patchCollectionRule(target.path.collection_id, savedRule);
      this.feedback.success("Collection rule saved.");
    });
  }

  removeRule() {
    return this.perform(async () => {
      const target = this.target;
      await this.removeRuleRequest.mutateAsync(target);
      patchCollectionRule(target.path.collection_id, null);
      this.feedback.success("Collection rule removed.");
    });
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
