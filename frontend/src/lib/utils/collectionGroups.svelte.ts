import { createMutation, createQuery } from "@tanstack/svelte-query";
import {
  deleteCollectionGroupMutation,
  listCollectionGroupsOptions,
  renameCollectionGroupMutation,
} from "../../generated/rest/@tanstack/svelte-query.gen";
import type { CollectionGroupDelete } from "../../generated/rest/types.gen";
import { chooseAction, confirmAction, createNotifier } from "../stores/notificationState.svelte";
import { errorMessage } from "./errors";

/** Actions for the selected group; the popup owns which group is selected. */
export class CollectionGroupActions {
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
      await this.renameRequest.mutateAsync({
        query: { name: this.group() },
        body: { name },
      });
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
      const result = await this.deleteRequest.mutateAsync({
        query: { name: this.group() },
        body,
      });
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
    return confirmed ? { collections: "keep", group: null } : null;
  }
  private async chooseScope(): Promise<CollectionGroupDelete | null> {
    const options: { body: CollectionGroupDelete; label: string; description?: string }[] = [
      { body: { collections: "keep", group: null }, label: "Move them to Ungrouped" },
      ...this.others().map((group) => ({
        body: { collections: "move" as const, group },
        label: `Move them to ${group}`,
      })),
      {
        body: { collections: "overture", group: null },
        label: "Remove them from Overture",
        description: "The server keeps them, and the next library sync lists them as Unmanaged.",
      },
      {
        body: { collections: "both", group: null },
        label: "Remove them from Overture and the media server",
      },
    ];
    const chosen = await chooseAction({
      title: `Delete group "${this.group()}"?`,
      message: "Choose what happens to its collections. Media files are always kept.",
      confirmLabel: "Delete group",
      destructive: true,
      choices: options.map(({ label, description }) => ({ value: label, label, description })),
    });
    return options.find((option) => option.label === chosen)?.body ?? null;
  }
}

/** Every collection group's name, as runs that choose groups by name list them. */
export function collectionGroupNames(enabled: () => boolean): () => string[] {
  const query = createQuery(() => ({ ...listCollectionGroupsOptions(), enabled: enabled() }));
  return () => query.data ?? [];
}
