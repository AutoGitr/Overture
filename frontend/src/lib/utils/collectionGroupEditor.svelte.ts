import { createQuery } from "@tanstack/svelte-query";
import {
  getCollectionGroupPolicyOptions,
  listCollectionGroupsOptions,
  listCollectionsOptions,
} from "../../generated/rest/@tanstack/svelte-query.gen";
import type { CollectionRead, LibrarySectionRead } from "../../generated/rest/types.gen";
import { queryClient } from "../rest/queryClient";
import { goToCollectionsList, goToGroup } from "../router/routes";
import { createNotifier } from "../stores/notificationState.svelte";
import { CollectionExport } from "./collectionExport.svelte";
import { CollectionGroupForm } from "./collectionGroupForm.svelte";
import { CollectionGroupActions } from "./collectionGroups.svelte";
import { openSync } from "./syncShortcut";

/** A group's page: its defaults, its set, its collections, and what can be done to it. */
export class CollectionGroupEditor {
  readonly creating = false;
  readonly form: CollectionGroupForm;
  readonly actions: CollectionGroupActions;
  readonly exporter = new CollectionExport();
  /** The saved group, which the form starts from. */
  readonly saved;
  private readonly collections = createQuery(() => listCollectionsOptions());
  private readonly groups = createQuery(() => listCollectionGroupsOptions());
  private readonly feedback = createNotifier();

  constructor(
    private readonly group: () => string,
    libraries: () => LibrarySectionRead[],
  ) {
    this.saved = createQuery(() => getCollectionGroupPolicyOptions({ path: { name: group() } }));
    this.form = new CollectionGroupForm(
      libraries,
      () => this.members.flatMap((row) => row.media_types),
      () => this.saved.data,
    );
    this.actions = new CollectionGroupActions(
      group,
      () => (this.groups.data ?? []).map((each) => each.name).filter((name) => name !== this.name),
      () => (this.collections.data ? this.members.length : null),
    );
  }

  get name() {
    return this.group();
  }
  /** The collections Overture manages in the group, its separator aside. */
  get members(): CollectionRead[] {
    return (this.collections.data ?? []).filter(
      (row) => row.managed && row.kind !== "separator" && row.collection_group === this.name,
    );
  }
  get defaults() {
    return this.form.defaults;
  }
  get capabilities() {
    return this.form.options.for(this.form.mediaTypes[0] ?? "movie");
  }
  get busy() {
    return this.form.busy || this.actions.busy || this.exporter.busy;
  }
  /** Nothing keeps a group from being saved. */
  readonly blocker = null;

  /** Start the form over from the saved group, as after a change saved elsewhere. */
  async reload() {
    this.form.reset(
      await queryClient.fetchQuery({
        ...getCollectionGroupPolicyOptions({ path: { name: this.name } }),
        staleTime: 0,
      }),
    );
  }

  /** Save in Overture; with `sync`, then open Sync with only this group chosen. */
  async save(sync = false) {
    const name = this.name;
    if (!(await this.form.save(name))) return false;
    if (sync) await openSync({ groups: [name] });
    else this.feedback.success(`Saved "${name}". Its collections get it with their next sync.`);
    return true;
  }

  async rename() {
    const name = await this.actions.rename();
    if (name) goToGroup(name);
  }

  async delete() {
    if (await this.actions.delete()) goToCollectionsList();
  }

  /** Download the group, its set and the collections it holds as a portable file. */
  export() {
    return this.exporter.run({ groups: [this.name] }, this.name);
  }
}
