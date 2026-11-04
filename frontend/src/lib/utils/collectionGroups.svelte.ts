import { createMutation, createQuery } from "@tanstack/svelte-query";
import {
  deleteCollectionGroupMutation,
  listCollectionGroupsOptions,
  renameCollectionGroupMutation,
} from "../../generated/rest/@tanstack/svelte-query.gen";
import type { CollectionGroupDelete, MediaType } from "../../generated/rest/types.gen";
import { chooseAction, createNotifier } from "../stores/notificationState.svelte";
import { errorMessage } from "./errors";

/** Actions for the selected group; the popup owns which group is selected. */
export class CollectionGroupActions {
  name = $derived.by(() => this.group());
  private readonly renameRequest = createMutation(() => renameCollectionGroupMutation());
  private readonly deleteRequest = createMutation(() => deleteCollectionGroupMutation());
  private readonly feedback = createNotifier();
  constructor(
    private readonly group: () => string,
    private readonly mediaType: () => MediaType,
    /** The other groups its collections can move to. */
    private readonly others: () => string[],
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
        query: { name: this.group(), media_type: this.mediaType() },
        body: { name },
      });
      this.feedback.success("Group renamed.");
      return name;
    } catch (error) {
      this.feedback.error(errorMessage(error, "Could not rename group"));
      return null;
    }
  }
  /** Ask what happens to its collections, then delete the group. */
  async delete(): Promise<boolean> {
    if (this.busy) return false;
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
    const body = options.find((option) => option.label === chosen)?.body;
    if (!body) return false;
    try {
      const result = await this.deleteRequest.mutateAsync({
        query: { name: this.group(), media_type: this.mediaType() },
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
}

/**
 * The names of every collection group across movies and shows, as runs that
 * choose groups by name list them. Create it during component initialisation.
 */
export function collectionGroupNames(enabled: () => boolean): () => string[] {
  const queries = (["movie", "show"] as const).map((media_type) =>
    createQuery(() => ({
      ...listCollectionGroupsOptions({ query: { media_type } }),
      enabled: enabled(),
    })),
  );
  return () => {
    const names = queries.flatMap((query) => query.data ?? []);
    return names.filter((name, index) => names.indexOf(name) === index);
  };
}
