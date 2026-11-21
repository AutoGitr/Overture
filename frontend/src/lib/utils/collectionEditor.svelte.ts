import { createMutation, createQuery } from "@tanstack/svelte-query";
import { SvelteMap, SvelteSet } from "svelte/reactivity";
import { UNGROUPED_GROUP } from "../../generated/settings";
import {
  deleteCollectionMutation,
  getCollectionDefaultsOptions,
  orphanCollectionMutation,
  saveCollectionRuleMutation,
  setCollectionMembersMutation,
  updateCollectionMutation,
} from "../../generated/rest/@tanstack/svelte-query.gen";
import type {
  CollectionDetail,
  CollectionOrder,
  CollectionRuleWriteInput,
  DeleteCollectionData,
  FilterGroupInput,
  LibrarySectionRead,
  MediaItemRead,
  MediaType,
} from "../../generated/rest/types.gen";
import { patchCollectionRule, storeCollectionDetail } from "../rest/cache";
import { closeCollection } from "../router/routes";
import { chooseAction, confirmAction, createNotifier } from "../stores/notificationState.svelte";
import { settingsState } from "../stores/settingsState.svelte";
import { emptyGroup } from "./collectionCriteria";
import {
  CollectionRuleForm,
  defaultRule,
  optionsBody,
  ruleBody,
  setLibrary,
} from "./collectionFormShared.svelte";
import { CriteriaPreview } from "./criteriaPreview.svelte";
import { errorMessage } from "./errors";
import { CollectionOptions as Capabilities } from "./libraries.svelte";
import { openSync } from "./syncShortcut";

/** Form drafts and actions for one mounted collection. */
export class CollectionEditor extends CollectionRuleForm {
  readonly defaults;
  readonly options: Capabilities;
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
  private readonly deleteRequest = createMutation(() => deleteCollectionMutation());
  private readonly orphanRequest = createMutation(() => orphanCollectionMutation());
  private readonly feedback = createNotifier();

  /** Edits a collection Overture manages; an unmanaged one is only adopted. */
  constructor(
    private readonly current: () => CollectionDetail,
    private readonly libraries: () => LibrarySectionRead[],
  ) {
    super();
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
    // Last: their queries read the form as soon as they are created.
    this.options = new Capabilities(() =>
      this.libraryIds.map((id) => ({ id, media_type: this.typeOf(id) })),
    );
    this.preview = new CriteriaPreview(
      () => this,
      () => this.collectionId,
    );
  }

  get collection() {
    return this.current();
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
    const memberIds = new SvelteSet(this.collection.member_ids);
    return libraryItems.filter(
      (item) =>
        item.copies.some((copy) => this.collection.library_ids.includes(copy.library_id)) &&
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
      this.deleteRequest.isPending ||
      this.orphanRequest.isPending
    );
  }

  /** The saved collection this edits. */
  get collectionId(): number {
    return this.current().id;
  }

  private get target() {
    return { path: { collection_id: this.collectionId } };
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

  /** Save in Overture; with `sync`, then open Sync with only this collection chosen. */
  save(sync = false) {
    // Snapshot options before persistRule resets drafts or remounts the view.
    const options = { ...this.target, body: optionsBody(this) };
    return this.perform(async () => {
      const rule = await this.persistRule();
      const saved = await this.updateRequest.mutateAsync(options);
      storeCollectionDetail(saved);
      if (rule !== undefined) patchCollectionRule(saved.id, rule);
      if (sync) await openSync({ collectionIds: [saved.id] });
      else this.feedback.success("Saved. Its next sync sends the changes to the server.");
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
          ...this.target,
          body: { member_ids: memberIds, order_type: order },
        }),
      );
    });
  }

  removeMember(id: number) {
    return this.setMembers(this.collection.member_ids.filter((member) => member !== id));
  }

  addMember(id: number) {
    if (this.collection.member_ids.includes(id)) return Promise.resolve(false);
    return this.setMembers([...this.collection.member_ids, id]);
  }

  moveMember(id: number, targetIndex: number) {
    const ids = [...this.collection.member_ids];
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

  /** Why the collection cannot be deleted: its set would make it again. */
  get deleteBlocker(): string | null {
    return this.generated ? "Its group's set made it; remove its value from the set" : null;
  }

  /** The servers holding a copy of it, or that a sync puts it on, as users know them. */
  get holders(): string {
    const { copies } = this.collection;
    return copies.length
      ? settingsState.serverNames(copies.map((copy) => copy.server_id))
      : settingsState.media_server_name;
  }

  /** Why Overture cannot stop managing it, or null when it can. */
  get orphanBlocker(): string | null {
    if (this.collection.withheld)
      return `It is not on ${settingsState.media_server_name}; delete it instead`;
    return this.deleteBlocker;
  }

  /** Stop managing it; the server keeps it, and it moves to Unmanaged. */
  async orphan() {
    if (
      this.orphanBlocker ||
      !(await confirmAction({
        title: "Orphan collection?",
        message: `Overture forgets the criteria, group and schedule of ${this.collection.title} and lists it under Unmanaged. ${this.holders} keeps it as it is; adopt it again to manage it.`,
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
    if (this.deleteBlocker) return;
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
          label: `From ${this.holders} only`,
          description:
            "Overture keeps its configuration, so a later manual or scheduled sync can recreate it.",
          unavailable: this.collection.withheld
            ? `It is not on ${settingsState.media_server_name}.`
            : undefined,
        },
        { value: "both", label: `From Overture and ${this.holders}` },
      ],
    });
    if (!target) return;
    await this.perform(async () => {
      await this.deleteRequest.mutateAsync({ ...this.target, query: { target } });
      if (target === "both") closeCollection();
    });
  }
}
