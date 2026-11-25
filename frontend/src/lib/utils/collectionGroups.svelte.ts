import { settingsState } from "../stores/settingsState.svelte";
import { createMutation, createQuery } from "@tanstack/svelte-query";
import {
  deleteCollectionGroupMutation,
  listCollectionGroupsOptions,
  listCollectionsOptions,
  renameCollectionGroupMutation,
} from "../../generated/rest/@tanstack/svelte-query.gen";
import type { CollectionGroupDelete } from "../../generated/rest/types.gen";
import { chooseAction, confirmAction, createNotifier } from "../stores/notificationState.svelte";
import { syncSelection } from "../stores/syncSelection.svelte";
import { renameAssetsGroup } from "./assetsForm.svelte";
import { errorMessage } from "./errors";
import type { ChoosableCollection } from "./popupSelection";
import { toOptions, type SelectOption } from "./selectOptions";

/** The groups a collection can join, by name, with the one it *held* among them. */
export function groupOptions(groups: readonly string[], held = ""): SelectOption[] {
  const names = [...groups, ...(held ? [held] : [])];
  return toOptions(
    names.filter((name, index) => names.indexOf(name) === index).sort((a, b) => a.localeCompare(b)),
  );
}

/** Rename and delete the group a page shows. */
export class CollectionGroupActions {
  /** The name it is renamed to, starting as its own. */
  name = $derived.by(() => this.group());
  private readonly renameRequest = createMutation(() => renameCollectionGroupMutation());
  private readonly deleteRequest = createMutation(() => deleteCollectionGroupMutation());
  private readonly feedback = createNotifier();
  constructor(
    private readonly group: () => string,
    /** The other groups its collections can move to. */
    private readonly others: () => string[],
    /** How many collections the group holds, or null until that is known. */
    private readonly members: () => number | null,
  ) {}
  get busy() {
    return this.renameRequest.isPending || this.deleteRequest.isPending;
  }
  get deleting() {
    return this.deleteRequest.isPending;
  }
  async rename(): Promise<string | null> {
    if (this.busy || !this.name.trim()) return null;
    const name = this.name.trim();
    try {
      await this.renameRequest.mutateAsync({ path: { name: this.group() }, body: { name } });
      syncSelection.renameGroup(this.group(), name);
      renameAssetsGroup(this.group(), name);
      this.feedback.success("Group renamed.");
      return name;
    } catch (error) {
      this.feedback.error(errorMessage(error, "Could not rename group"));
      return null;
    }
  }
  /** Ask what happens to its collections, if it has any, then delete the group. */
  async delete(): Promise<boolean> {
    if (this.busy) return false;
    const body = this.members() === 0 ? await this.confirmEmpty() : await this.chooseScope();
    if (!body) return false;
    try {
      const result = await this.deleteRequest.mutateAsync({ path: { name: this.group() }, body });
      const errors = Object.values(result.errors);
      if (errors.length) {
        this.feedback.error(
          `The group was kept because ${errors.length} collection operations failed: ${errors.join("; ")}`,
        );
        return false;
      }
      this.feedback.success("Group deleted.");
      return true;
    } catch (error) {
      this.feedback.error(errorMessage(error, "Could not delete group"));
      return false;
    }
  }
  /** An empty group has no collections to decide about. */
  private async confirmEmpty(): Promise<CollectionGroupDelete | null> {
    const confirmed = await confirmAction({
      title: `Delete group "${this.group()}"?`,
      message: "It holds no collections; only its defaults are removed.",
      confirmLabel: "Delete group",
      destructive: true,
    });
    return confirmed ? {} : null;
  }
  private async chooseScope(): Promise<CollectionGroupDelete | null> {
    const options: { body: CollectionGroupDelete; label: string; description?: string }[] = [
      ...this.others().map((group) => ({
        body: { collections: "move" as const, group },
        label: `Move them to ${group}`,
      })),
      {
        body: { collections: "orphan" },
        label: "Orphan them",
        description: "Overture stops managing them; the server keeps them, listed under Unmanaged.",
      },
      {
        body: { collections: "both" },
        label: `Remove them from Overture and ${settingsState.media_server_name}`,
      },
    ];
    const chosen = await chooseAction({
      title: `Delete group "${this.group()}"?`,
      message: "Choose what happens to its collections. Media files are always kept.",
      confirmLabel: "Delete group",
      destructive: true,
      choices: options.map(({ label, description }, index) => ({
        value: String(index),
        label,
        description,
      })),
    });
    return chosen === null ? null : (options[Number(chosen)]?.body ?? null);
  }
}

/** Every collection group's name, as runs that choose groups list them. */
export function collectionGroupNames(enabled: () => boolean): () => string[] {
  const query = createQuery(() => ({ ...listCollectionGroupsOptions(), enabled: enabled() }));
  const names = $derived((query.data ?? []).map((group) => group.name));
  return () => names;
}

/** The collections a run can choose one by one: those Overture manages, by title. */
export function choosableCollections(enabled: () => boolean): () => ChoosableCollection[] {
  const query = createQuery(() => ({ ...listCollectionsOptions(), enabled: enabled() }));
  const rows = $derived(
    (query.data ?? [])
      .flatMap((row) =>
        // Only a collection Overture manages is in a group, and every one is.
        row.managed && row.kind !== "separator" && row.collection_group
          ? [{ id: row.id, title: row.title, group: row.collection_group }]
          : [],
      )
      .sort((a, b) => a.title.localeCompare(b.title)),
  );
  return () => rows;
}
