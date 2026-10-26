import { createMutation } from "@tanstack/svelte-query";
import {
  deleteCollectionGroupMutation,
  renameCollectionGroupMutation,
} from "../../generated/rest/@tanstack/svelte-query.gen";
import type { CollectionGroupDelete, MediaType } from "../../generated/rest/types.gen";
import { confirmAction, createNotifier } from "../stores/notificationState.svelte";
import { errorMessage } from "./errors";

/** Actions for the selected group; the popup owns which group is selected. */
export class CollectionGroupActions {
  name = $derived.by(() => this.group());
  removal = $state<CollectionGroupDelete["collections"]>("keep");
  private readonly renameRequest = createMutation(() => renameCollectionGroupMutation());
  private readonly deleteRequest = createMutation(() => deleteCollectionGroupMutation());
  private readonly feedback = createNotifier();
  constructor(
    private readonly group: () => string,
    private readonly mediaType: () => MediaType,
  ) {}
  get busy() {
    return this.renameRequest.isPending || this.deleteRequest.isPending;
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
  async delete(): Promise<boolean> {
    if (this.busy) return false;
    const removal = this.removal ?? "keep";
    const descriptions = {
      keep: "Keep all collections and remove their group assignment.",
      overture:
        "Remove its collections from Overture. Server collections are kept and can be imported again by a library sync.",
      server:
        "Remove its collections from the media server. Keep their Overture configuration with scheduled sync disabled.",
      both: "Remove its collections from both Overture and the media server.",
    };
    if (
      !(await confirmAction({
        title: `Delete group "${this.group()}"?`,
        message: `${descriptions[removal]} Media files are kept.`,
        confirmLabel: "Delete group",
        destructive: true,
      }))
    )
      return false;
    try {
      const result = await this.deleteRequest.mutateAsync({
        query: { name: this.group(), media_type: this.mediaType() },
        body: { collections: removal },
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
