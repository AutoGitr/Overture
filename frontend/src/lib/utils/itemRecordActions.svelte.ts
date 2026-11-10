import { createMutation } from "@tanstack/svelte-query";
import {
  deleteItemMutation,
  removeAllArtMutation,
  removeArtMutation,
  removeThemeMutation,
  setMonitoredMutation,
} from "../../generated/rest/@tanstack/svelte-query.gen";
import type { MediaItemRead } from "../../generated/rest/types.gen";
import { upsertLibraryItem } from "../rest/cache";
import { goToLibrary, type ArtSubTab } from "../router/routes";
import { downloadState } from "../stores/downloadState.svelte";
import { confirmAction, createNotifier } from "../stores/notificationState.svelte";
import { askRemoval } from "./assetRemoval";
import { errorMessage } from "./errors";

/**
 * What the detail view can do to a stored item's record: remove its art or
 * theme, monitor it or remove it. Changed items arrive over the live connection, so
 * only the server's own answers are written to the cache here. Create it
 * during component initialisation.
 */
export class ItemRecordActions {
  readonly #feedback = createNotifier();
  readonly #clearAllArt = createMutation(() => removeAllArtMutation());
  readonly #clearArt = createMutation(() => removeArtMutation());
  readonly #clearTheme = createMutation(() => removeThemeMutation());
  readonly #setMonitored = createMutation(() => setMonitoredMutation());
  readonly #delete = createMutation(() => deleteItemMutation());

  constructor(private readonly item: () => MediaItemRead | null) {}

  get clearingArt(): boolean {
    return this.#clearArt.isPending || this.#clearAllArt.isPending;
  }

  get themeBusy(): boolean {
    const item = this.item();
    return (
      this.#clearTheme.isPending ||
      (!!item &&
        downloadState
          .getJobsForItem(item.id)
          .some((job) => job.job_type === "theme" && job.status === "running"))
    );
  }

  get monitoring(): boolean {
    return this.#setMonitored.isPending;
  }

  get deleting(): boolean {
    return this.#delete.isPending;
  }

  /** Remove a tab's art, or only the season being viewed. */
  async clearArt(tab: ArtSubTab, seasonId: number | null = null): Promise<void> {
    const item = this.item();
    if (!item || this.clearingArt) return;
    const artType = tab === "seasons" ? "season_poster" : tab;
    await this.#run("Remove art failed", async () => {
      const removal = await askRemoval(
        { asset: artType, item_ids: [item.id], season_id: seasonId },
        seasonId === null && tab === "seasons" ? "every season poster" : `the ${tab}`,
      );
      if (!removal) return;
      await this.#clearArt.mutateAsync({
        path: { item_id: item.id, art_type: artType },
        query: { ...removal, ...(seasonId === null ? {} : { season_id: seasonId }) },
      });
    });
  }

  async clearAllArt(): Promise<void> {
    const item = this.item();
    if (!item || this.clearingArt) return;
    await this.#run("Remove all art failed", async () => {
      const removal = await askRemoval({ asset: "art", item_ids: [item.id] }, "all of its art");
      if (!removal) return;
      await this.#clearAllArt.mutateAsync({ path: { item_id: item.id }, query: removal });
    });
  }

  async clearTheme(): Promise<void> {
    const item = this.item();
    if (!item || this.themeBusy) return;
    await this.#run("Remove theme failed", async () => {
      const removal = await askRemoval({ asset: "theme", item_ids: [item.id] }, "the theme");
      if (!removal) return;
      await this.#clearTheme.mutateAsync({ path: { item_id: item.id }, query: removal });
    });
  }

  async toggleMonitored(): Promise<void> {
    const item = this.item();
    if (!item) return;
    await this.#run("Toggle monitored failed", async () => {
      const { monitored } = await this.#setMonitored.mutateAsync({
        path: { item_id: item.id },
        body: { monitored: !item.monitored },
      });
      upsertLibraryItem({ ...item, monitored });
    });
  }

  async delete(): Promise<void> {
    const item = this.item();
    if (!item) return;
    const confirmed = await confirmAction({
      title: `Remove ${item.title ?? "this item"} from Overture?`,
      message:
        "Its saved record will be removed. Local files and the media server item are kept, so it may return after a sync.",
      confirmLabel: "Remove",
      destructive: true,
    });
    if (!confirmed) return;
    await this.#run("Delete item failed", async () => {
      await this.#delete.mutateAsync({ path: { item_id: item.id } });
      goToLibrary(item.media_type);
    });
  }

  async #run(failure: string, action: () => Promise<unknown>): Promise<void> {
    this.#feedback.clear();
    try {
      await action();
    } catch (err) {
      this.#feedback.error(errorMessage(err, failure));
    }
  }
}
